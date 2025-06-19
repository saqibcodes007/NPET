import os
import io
import pandas as pd
import zeep
import zeep.helpers
from zeep.exceptions import Fault as SoapFault
import datetime
from dateutil.parser import parse as parse_date
from flask import Flask, request, render_template, send_file, session
import tempfile
import uuid
import pgeocode

# Initialize Flask App & Geo-lookup tool
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'a_secure_fallback_key_for_development')
GEO_LOOKUP = pgeocode.Nominatim('us')

# Tebra API Configuration
TEBRA_WSDL_URL = "https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?singleWsdl"

# --- Function to Normalize Practice Names ---
def normalize_practice_name(name_from_excel):
    if not isinstance(name_from_excel, str):
        return ''
    clean_name = name_from_excel.strip().lower()
    if 'pedia' in clean_name or 'west' in clean_name or clean_name == 'pw':
        return 'PEDIATRICS WEST'
    if 'pamela' in clean_name or 'johnson' in clean_name:
        return 'PAMELA JOHNSON PT'
    if 'berlin' in clean_name or clean_name == 'nbms':
        return 'New Berlin Medical Services LLC'
    if 'person' in clean_name or 'surgical' in clean_name or clean_name == 'psa':
        return 'PERSON SURGICAL ASSOCIATES'
    return name_from_excel

# --- Tebra API Functions (Unchanged) ---
def create_api_client(wsdl_url):
    try:
        from requests import Session
        from zeep.transports import Transport
        session = Session()
        session.timeout = 60
        transport = Transport(session=session, timeout=60)
        client = zeep.Client(wsdl=wsdl_url, transport=transport)
        return client
    except Exception as e:
        print(f"❌ Failed to connect to Tebra API. Details: {e}")
        return None

def build_request_header(credentials, client):
    if not client: return None
    try:
        password = credentials['Password']
        password = password.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;').replace("'", '&apos;')
        header_type = client.get_type('ns0:RequestHeader')
        request_header = header_type(
            CustomerKey=credentials['CustomerKey'],
            User=credentials['User'],
            Password=password
        )
        return request_header
    except Exception as e:
        print(f"❌ Error building request header: {e}")
        return None

def normalize_gender(gender_string):
    if not isinstance(gender_string, str): return "Unknown"
    g = gender_string.strip().lower()
    if g.startswith('m'): return "Male"
    if g.startswith('f'): return "Female"
    return "Unknown"

def create_patient_in_tebra(client, header, patient_data):
    if not client or not header:
        return {"Error": "API client or request header is not available."}
    try:
        CreatePatientReqType = client.get_type('ns0:CreatePatientReq')
        PatientCreateType = client.get_type('ns0:PatientCreate')
        PracticeIdentifierReqType = client.get_type('ns0:PracticeIdentifierReq')
        PatientCaseCreateReqType = client.get_type('ns0:PatientCaseCreateReq')

        practice_obj = PracticeIdentifierReqType(PracticeName=patient_data.get("Practice"))
        default_case_obj = PatientCaseCreateReqType(CaseName="Initial Record", Active=True)
        cases_to_create = [default_case_obj]

        dob_string = patient_data.get("DOB")
        if not dob_string:
            return {"Error": "DOB field is missing or empty."}
        try:
            dob_datetime = parse_date(dob_string)
        except (ValueError, TypeError):
             return {"Error": f"Invalid date format for DOB: '{dob_string}'."}

        patient_obj = PatientCreateType(
            FirstName=patient_data.get("First Name"),
            LastName=patient_data.get("Last Name"),
            DateofBirth=dob_datetime,
            Gender=patient_data.get("Gender"),
            Practice=practice_obj,
            Cases=cases_to_create,
            AddressLine1=patient_data.get("Address"),
            City=patient_data.get("City"),
            State=patient_data.get("State"),
            ZipCode=patient_data.get("Zip Code"),
            EmailAddress=patient_data.get("Email Address"),
            SocialSecurityNumber=patient_data.get("Social Security Number (SSN)"),
            MedicalRecordNumber=patient_data.get("Medical Record Number (MRN)"),
            MobilePhone=patient_data.get("Mobile Phone"),
            HomePhone=patient_data.get("Home Phone")
        )
        create_patient_request = CreatePatientReqType(RequestHeader=header, Patient=patient_obj)
        response = client.service.CreatePatient(request=create_patient_request)

        if response.ErrorResponse and response.ErrorResponse.IsError:
            return {"Error": response.ErrorResponse.ErrorMessage}
        else:
            patient_id_created = response.PatientID
            case_ids_created = []
            if response.Cases and hasattr(response.Cases, 'PatientCaseRes') and response.Cases.PatientCaseRes:
                for case_res_item in response.Cases.PatientCaseRes:
                    if case_res_item and hasattr(case_res_item, 'CaseID'):
                        case_ids_created.append(case_res_item.CaseID)
            return {"PatientID": patient_id_created, "CaseIDs": ", ".join(map(str, case_ids_created)), "Error": "Success"}
    except SoapFault as fault:
        return {"Error": f"SOAP Fault: {fault.message}"}
    except Exception as e:
        return {"Error": f"An unexpected error occurred: {str(e)}"}

#<-- FLASK WEB ROUTES -->
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        credentials = {"CustomerKey": request.form['customer_key'], "User": request.form['user'], "Password": request.form['password']}
        uploaded_file = request.files['patient_file']

        if not uploaded_file: return "No file uploaded!", 400

        try:
            df = pd.read_excel(uploaded_file, engine='openpyxl', dtype=str).fillna('')
            column_map = {
                'Practice': ['practice', 'practice name'], 'First Name': ['first name', 'firstname', 'first'],
                'Last Name': ['last name', 'lastname', 'last', 'surname'], 'DOB': ['dob', 'date of birth', 'birthdate'],
                'Gender': ['gender', 'sex'], 'Address': ['address', 'address line 1', 'addressline1'],
                'Zip Code': ['zip', 'zip code', 'zipcode', 'postal code', 'postalcode'],
                'Email Address': ['email', 'email address'], 'Social Security Number (SSN)': ['ssn', 'social security number'],
                'Medical Record Number (MRN)': ['mrn', 'medical record number'],
                'Mobile Phone': ['mobile phone', 'mobile', 'cell phone'], 'Home Phone': ['home phone', 'phone']
            }
            df.columns = [col.strip().lower() for col in df.columns]
            processed_df = pd.DataFrame()
            for standard_col, variations in column_map.items():
                for var in variations:
                    if var in df.columns:
                        processed_df[standard_col] = df[var]
                        break
                if standard_col not in processed_df:
                    processed_df[standard_col] = ''

            required_cols = ['Practice', 'First Name', 'Last Name', 'DOB', 'Gender']
            for col in required_cols:
                 if (processed_df[col] == '').all():
                     return f"Missing required column or data for: {col}.", 400
        except Exception as e:
            return f"Error reading Excel file: {e}", 400

        client = create_api_client(TEBRA_WSDL_URL)
        if not client: return "Failed to connect to Tebra API.", 500
        header = build_request_header(credentials, client)
        if not header: return "Failed to build Tebra API request header.", 500
        
        results_list = []
        processed_records = [] # This will store the fully cleaned records
        records_to_process = processed_df.to_dict(orient='records')

        for record in records_to_process:
            # We work on a copy that will be sent to Tebra and used for our output
            cleaned_record = record.copy()
            
            # --- Apply all normalizations to the cleaned_record ---
            cleaned_record['Practice'] = normalize_practice_name(record.get('Practice'))
            cleaned_record['Gender'] = normalize_gender(record.get('Gender'))
            
            zip_code = record.get('Zip Code')
            if zip_code and isinstance(zip_code, str) and zip_code.strip():
                location_info = GEO_LOOKUP.query_postal_code(zip_code.strip())
                if pd.notna(location_info.place_name):
                    cleaned_record['City'] = location_info.place_name
                    cleaned_record['State'] = location_info.state_code
            
            # Add the fully cleaned record to our list for the final output table
            processed_records.append(cleaned_record)
            
            # Send the cleaned data to the Tebra API
            result = create_patient_in_tebra(client, header, cleaned_record)
            results_list.append(result)
        
        # --- MODIFICATION: Build the final DataFrame from the CLEANED records ---
        final_output_df = pd.DataFrame(processed_records)
        
        # Add the API result columns to this cleaned DataFrame
        results_df = pd.DataFrame(results_list)
        final_output_df['Patient ID'] = results_df['PatientID'].fillna('N/A')
        final_output_df['Case ID'] = results_df['CaseIDs'].fillna('N/A')
        final_output_df['API Status'] = results_df['Error'].fillna('Unknown Error')

        if 'DOB' in final_output_df.columns:
            final_output_df['DOB'] = pd.to_datetime(final_output_df['DOB'], errors='coerce').dt.strftime('%m-%d-%Y')
            final_output_df['DOB'] = final_output_df['DOB'].fillna('Invalid Date')

        # Save to a temp file
        output_buffer = io.BytesIO()
        final_output_df.to_excel(output_buffer, index=False, sheet_name='Tebra_Creation_Results')
        output_buffer.seek(0)
        
        temp_dir = tempfile.gettempdir()
        unique_filename = f"tebra_output_{uuid.uuid4().hex}.xlsx"
        temp_path = os.path.join(temp_dir, unique_filename)
        
        with open(temp_path, 'wb') as f:
            f.write(output_buffer.getvalue())
        session['output_file_path'] = temp_path

        final_results_for_html = final_output_df.to_dict(orient='records')
        return render_template('index.html', results=final_results_for_html)

    return render_template('index.html', results=None)

@app.route('/download')
def download_file():
    output_file_path = session.get('output_file_path')
    if not output_file_path or not os.path.exists(output_file_path):
        return "No file to download. Please process a file first.", 404
    return send_file(
        output_file_path,
        as_attachment=True,
        download_name='tebra_output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

if __name__ == '__main__':
    app.run(debug=True)
