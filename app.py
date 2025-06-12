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
import json # For logging

# Initialize Flask App
app = Flask(__name__)
# Load secret key from environment variable for production
app.secret_key = os.environ.get('SECRET_KEY', 'a_secure_fallback_key_for_development')

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

# def format_dob_for_api_ddmmyyyy(dob_string):
#     """
#     Parses various date formats and converts to DD-MM-YYYY string for the API function.
#     """
#     try:
#         dt_object = parse_date(dob_string)
#         return dt_object.strftime("%d-%m-%Y")
#     except (ValueError, TypeError):
#         print(f"❌ Could not parse date: {dob_string}.")
#         return None

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

# MODIFIED: Renamed function and expanded to include all optional fields
def create_patient_in_tebra(client, header, patient_data):
    """
    Creates a new patient with optional details and a default case in Tebra PMS.
    """
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

        # --- MODIFIED DOB HANDLING START ---
        # This block now directly parses the date string from the Excel file
        # It robustly handles formats like MM/DD/YYYY and MM-DD-YYYY
        dob_string = patient_data.get("DOB")
        if not dob_string:
            return {"Error": "DOB field is missing or empty."}
        try:
            # Use the flexible parse_date from dateutil
            dob_datetime = parse_date(dob_string)
        except (ValueError, TypeError):
             return {"Error": f"Invalid date format for DOB: '{dob_string}'. Please use MM/DD/YYYY."}
        # --- MODIFIED DOB HANDLING END ---

        # MODIFIED: Expanded PatientCreateType to include all new optional fields
        patient_obj = PatientCreateType(
            # Required Fields
            FirstName=patient_data.get("First Name"),
            LastName=patient_data.get("Last Name"),
            DateofBirth=dob_datetime,
            Gender=patient_data.get("Gender"),
            Practice=practice_obj,
            Cases=cases_to_create,

            # Optional Fields
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
    # ADDED: Logging to diagnose cleanup
    print("DEBUG: Cleanup function has been triggered.")
    for temp_path in list(TEMP_FILES):
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
                TEMP_FILES.remove(temp_path)
        except Exception as e:
            print(f"Failed to remove temp file {temp_path}: {e}")

# MODIFIED: Commented out for Azure stability
# atexit.register(cleanup_temp_files)

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
# MODIFIED: Commented out for Azure stability
# periodic_temp_cleanup()


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
            df = pd.read_excel(uploaded_file, engine='openpyxl', dtype=str).fillna('')
            
            # MODIFIED: Expanded column_map for all required and optional fields
            column_map = {
                # Required
                'Practice': ['practice', 'practice name'],
                'First Name': ['first name', 'firstname', 'first'],
                'Last Name': ['last name', 'lastname', 'last', 'surname'],
                'DOB': ['dob', 'date of birth', 'birthdate'],
                'Gender': ['gender', 'sex'],
                # Optional
                'Address': ['address', 'address line 1', 'addressline1'],
                'City': ['city'],
                'State': ['state', 'province'],
                'Zip Code': ['zip', 'zip code', 'zipcode', 'postal code', 'postalcode'],
                'Email Address': ['email', 'email address'],
                'Social Security Number (SSN)': ['ssn', 'social security number'],
                'Medical Record Number (MRN)': ['mrn', 'medical record number'],
                'Mobile Phone': ['mobile phone', 'mobile', 'cell phone'],
                'Home Phone': ['home phone', 'phone']
            }

            # Normalize column names in the DataFrame for mapping
            df.columns = [col.strip().lower() for col in df.columns]
            
            # Build a new DataFrame with standardized column names
            processed_df = pd.DataFrame()
            final_columns = list(column_map.keys())
            
            for standard_col, variations in column_map.items():
                found = False
                for var in variations:
                    if var in df.columns:
                        processed_df[standard_col] = df[var]
                        found = True
                        break
                if not found:
                    # If a required column is not found, add an empty column
                    processed_df[standard_col] = ''

            required_cols = ['Practice', 'First Name', 'Last Name', 'DOB', 'Gender']
            # Check if required columns have any data
            for col in required_cols:
                 if processed_df[col].isnull().all() or (processed_df[col] == '').all():
                     return f"Missing required column or data for: {col}. Please ensure the Excel file has: {', '.join(required_cols)}", 400

        except Exception as e:
            return f"Error reading Excel file: {e}", 400

        client = create_api_client(TEBRA_WSDL_URL)
        if not client:
            return "Failed to connect to Tebra API. Check credentials or network.", 500
        
        header = build_request_header(credentials, client)
        if not header:
            return "Failed to build Tebra API request header. Check credentials.", 500
        
        results_list = []
        # MODIFIED: Convert DataFrame to dictionary records for easier processing
        # Replace NaN with None for better compatibility
        processed_df = processed_df.where(pd.notna(processed_df), None)
        records_to_process = processed_df.to_dict(orient='records')

        # --- MODIFIED LOOP START ---
        for record in records_to_process:
            # Prepare data for this specific patient
            patient_data_to_create = record.copy()
            # We no longer need to pre-format the DOB. It's passed directly.
            patient_data_to_create['Gender'] = normalize_gender(record['Gender'])
            
            result = create_patient_in_tebra(client, header, patient_data_to_create)

            results_list.append(result)
        # --- MODIFIED LOOP END ---
        
        # Combine original data with the results
        results_df = pd.DataFrame(results_list)
        final_output_df = processed_df.copy()
        final_output_df['Patient ID'] = results_df['PatientID'].fillna('N/A')
        final_output_df['Case ID'] = results_df['CaseIDs'].fillna('N/A')
        final_output_df['API Status'] = results_df['Error'].fillna('Unknown Error')
        
        # Save to a temp file and store the filename in the session
        # This logic relies on ARR Affinity being ON in Azure
        output_buffer = io.BytesIO()
        final_output_df.to_excel(output_buffer, index=False, sheet_name='Tebra_Creation_Results')
        output_buffer.seek(0)
        
        temp_dir = tempfile.gettempdir()
        unique_filename = f"tebra_output_{uuid.uuid4().hex}.xlsx"
        temp_path = os.path.join(temp_dir, unique_filename)
        
        # ADDED: Logging to diagnose file creation
        print(f"DEBUG: File successfully created at {temp_path}")
        with open(temp_path, 'wb') as f:
            f.write(output_buffer.getvalue())
            
        session['output_file_path'] = temp_path
        TEMP_FILES.add(temp_path)

        final_results_for_html = final_output_df.to_dict(orient='records')
        return render_template('index.html', results=final_results_for_html)

    return render_template('index.html', results=None)

@app.route('/download')
def download_file():
    """Provides the generated Excel file for download."""
    output_file_path = session.get('output_file_path')
    
    # ADDED: Logging to diagnose download
    print(f"DEBUG: Download triggered. Attempting to access path: {output_file_path}")

    if not output_file_path or not os.path.exists(output_file_path):
        print(f"DEBUG: File check failed. Path was '{output_file_path}' and os.path.exists is {os.path.exists(output_file_path) if output_file_path else 'False'}.")
        return "No file to download. Please process a file first.", 404
    
    print(f"DEBUG: File found at {output_file_path}. Preparing for download.")
    return send_file(
        output_file_path,
        as_attachment=True,
        download_name='tebra_output.xlsx',
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

if __name__ == '__main__':
    app.run(debug=True)
