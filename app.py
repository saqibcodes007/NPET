import os
import io
import pandas as pd
import zeep
import zeep.helpers
from zeep.exceptions import Fault as SoapFault
import datetime
from dateutil.parser import parse as parse_date # Robust date parser
from flask import Flask, request, render_template, send_file, session, url_for, redirect
import tempfile
import uuid
import atexit
import glob

# Initialize Flask App
app = Flask(__name__)
# Secret key is needed for session management (to store the output file path)
app.secret_key = os.urandom(24) 

# --- Tebra API Configuration ---
TEBRA_WSDL_URL = "https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?singleWsdl"

#<-- FROM YOUR SCRIPT: Tebra API Functions -->
def create_api_client(wsdl_url):
    """Creates and returns a Zeep client for the Tebra SOAP API."""
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
    """Builds the request header for Tebra API calls."""
    if not client: return None
    try:
        password = credentials['Password']
        # Escape special XML characters
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

def format_dob_for_api_ddmmyyyy(dob_string):
    """
    Parses various date formats and converts to DD-MM-YYYY string for the API function.
    """
    try:
        dt_object = parse_date(dob_string)
        return dt_object.strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        print(f"❌ Could not parse date: {dob_string}.")
        return None

def normalize_gender(gender_string):
    """Normalizes various gender inputs to 'Male' or 'Female'."""
    if not isinstance(gender_string, str):
        return "Unknown"
    g = gender_string.strip().lower()
    if g.startswith('m'):
        return "Male"
    if g.startswith('f'):
        return "Female"
    return "Unknown"

def create_minimal_patient_with_default_case(client, header, patient_data):
    """
    Creates a new patient with minimal data and a default case in Tebra PMS.
    """
    if not client or not header:
        return {"Error": "API client or request header is not available."}

    try:
        CreatePatientReqType = client.get_type('ns0:CreatePatientReq')
        PatientCreateType = client.get_type('ns0:PatientCreate')
        PracticeIdentifierReqType = client.get_type('ns0:PracticeIdentifierReq')
        PatientCaseCreateReqType = client.get_type('ns0:PatientCaseCreateReq')

        practice_obj = PracticeIdentifierReqType(PracticeName=patient_data.get("PracticeName"))
        default_case_obj = PatientCaseCreateReqType(CaseName="Initial Record", Active=True)
        cases_to_create = [default_case_obj]

        dob_for_tebra = patient_data.get("DOB") 
        try:
            dob_datetime = datetime.datetime.strptime(dob_for_tebra, "%d-%m-%Y")
        except ValueError:
             return {"Error": f"Invalid final date format for DOB: {dob_for_tebra}."}

        patient_obj = PatientCreateType(
            FirstName=patient_data.get("FirstName"),
            LastName=patient_data.get("LastName"),
            DateofBirth=dob_datetime,
            Gender=patient_data.get("Gender"),
            Practice=practice_obj,
            Cases=cases_to_create
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
            
            return {
                "PatientID": patient_id_created,
                "CaseIDs": ", ".join(map(str, case_ids_created)),
                "Error": "Success"
            }

    except SoapFault as fault:
        return {"Error": f"SOAP Fault: {fault.message}"}
    except Exception as e:
        return {"Error": f"An unexpected error occurred: {str(e)}"}

#<-- FLASK WEB ROUTES -->

# Store temp file paths for cleanup
TEMP_FILES = set()

def cleanup_temp_files():
    for temp_path in list(TEMP_FILES):
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                TEMP_FILES.remove(temp_path)
        except Exception as e:
            print(f"Failed to remove temp file {temp_path}: {e}")

atexit.register(cleanup_temp_files)

# Optionally, clean up old temp files from previous runs (older than 1 day)
def periodic_temp_cleanup():
    temp_dir = tempfile.gettempdir()
    pattern = os.path.join(temp_dir, 'tebra_output_*.xlsx')
    now = datetime.datetime.now()
    for file_path in glob.glob(pattern):
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(file_path))
            if (now - mtime).days > 0:
                os.remove(file_path)
        except Exception:
            pass
periodic_temp_cleanup()

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        credentials = {
            "CustomerKey": request.form['customer_key'],
            "User": request.form['user'],
            "Password": request.form['password']
        }
        uploaded_file = request.files['patient_file']

        if not uploaded_file:
            return "No file uploaded!", 400

        try:
            df = pd.read_excel(uploaded_file, engine='openpyxl')
            
            column_map = {
                'Practice': ['practice', 'practice name'],
                'First Name': ['first name', 'firstname', 'first'],
                'Last Name': ['last name', 'lastname', 'last', 'surname'],
                'DOB': ['dob', 'date of birth', 'birthdate'],
                'Gender': ['gender', 'sex']
            }

            found_columns = {}
            for original_col in df.columns:
                for target_col, variations in column_map.items():
                    if original_col.strip().lower() in variations:
                        found_columns[target_col] = original_col
                        break
            
            required = ['Practice', 'First Name', 'Last Name', 'DOB', 'Gender']
            if not all(col in found_columns for col in required):
                return f"Missing required columns. Please ensure the Excel file has: {', '.join(required)}", 400

            processed_df = pd.DataFrame()
            for target, original in found_columns.items():
                processed_df[target] = df[original]

        except Exception as e:
            return f"Error reading Excel file: {e}", 400

        client = create_api_client(TEBRA_WSDL_URL)
        if not client:
            return "Failed to connect to Tebra API. Check credentials or network.", 500
        
        header = build_request_header(credentials, client)
        if not header:
            return "Failed to build Tebra API request header. Check credentials.", 500
        
        results_list = []
        for index, row in processed_df.iterrows():
            patient_data = {
                "PracticeName": row['Practice'],
                "FirstName": row['First Name'],
                "LastName": row['Last Name'],
                "DOB": format_dob_for_api_ddmmyyyy(str(row['DOB'])),
                "Gender": normalize_gender(row['Gender'])
            }
            
            if not patient_data["DOB"]:
                result = {"Error": "Invalid or unreadable DOB"}
            else:
                result = create_minimal_patient_with_default_case(client, header, patient_data)

            results_list.append(result)
        
        results_df = pd.DataFrame(results_list)
        processed_df['Patient ID'] = results_df['PatientID'].fillna('N/A')
        processed_df['Case ID'] = results_df['CaseIDs'].fillna('N/A')
        processed_df['Error/Results'] = results_df['Error'].fillna('Unknown Error')
        
        output_buffer = io.BytesIO()
        processed_df.to_excel(output_buffer, index=False, sheet_name='Tebra_Creation_Results')
        output_buffer.seek(0)

        # Save to a temp file and store the filename in the session
        temp_dir = tempfile.gettempdir()
        unique_filename = f"tebra_output_{uuid.uuid4().hex}.xlsx"
        temp_path = os.path.join(temp_dir, unique_filename)
        with open(temp_path, 'wb') as f:
            f.write(output_buffer.getvalue())
        session['output_file_path'] = temp_path
        TEMP_FILES.add(temp_path)

        final_results_for_html = processed_df.to_dict(orient='records')
        return render_template('index.html', results=final_results_for_html)
    return render_template('index.html', results=None)

@app.route('/download')
def download_file():
    """Provides the generated Excel file for download."""
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