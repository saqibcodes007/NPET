# NPET - New Patient Entry in Tebra

NPET is a Flask web application that allows users to upload Tebra credentials and an Excel file containing new patient data, then creates those patients in the Tebra Practice Management System (PMS).

## Features
- Securely upload Tebra credentials and patient Excel files
- Automatic mapping and validation of required columns
- Batch creation of patients in Tebra PMS
- Downloadable results Excel file with patient creation status
- Modern, responsive UI with Bootstrap

## Requirements
- Python 3.11+
- pip
- (Recommended) Virtual environment

## Setup Instructions

### 1. Clone the Repository
```powershell
git clone https://github.com/saqibcodes007/NPET.git
cd NPET
```

### 2. Create and Activate a Virtual Environment
```powershell
python -m venv .venv
.venv\Scripts\Activate
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 4. Run the Application Locally
```powershell
python app.py
```

The app will be available at [http://127.0.0.1:5000](http://127.0.0.1:5000).

## Usage
1. Open the app in your browser.
2. Enter your Tebra credentials (Customer Key, Username, Password).
3. Upload an Excel file with columns: Practice, First Name, Last Name, DOB, Gender.
4. Click "Create Patients in Tebra".
5. Download the output Excel file with results.

## Deployment to Azure

### Using Azure Portal and GitHub Actions
1. Push your code to a GitHub repository.
2. Create an Azure App Service (Python stack) via the Azure Portal.
3. In the App Service, go to **Deployment Center** and connect your GitHub repo.
4. Azure will generate a GitHub Actions workflow for CI/CD (see `.github/workflows`).
5. Add your App Service publish profile as a secret in your GitHub repo (`AZUREAPPSERVICE_PUBLISHPROFILE`).
6. Set your Flask secret key in the Azure Portal as an environment variable:  
   - Key: `SECRET_KEY`
   - Value: *(your secret key)*
7. Push to `main` to trigger deployment.

**Note**: The application uses Gunicorn for production environments.

## Security
- Credentials are not stored; they are used only for the session.
- Output Excel files are stored as temporary files and are only available for download within a session.
- Periodic cleanup removes old temporary files automatically.
- Set your Flask `SECRET_KEY` via environment variable for production security.

## License
MIT License

---
Developed by Saqib Sherwani | Panacea Smart Solutions
