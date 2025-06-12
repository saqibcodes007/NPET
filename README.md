# NPET (New Patient Entry in Tebra)

NPET is a Python (Flask) application designed to streamline the process of bulk uploading new patient data into Tebra (formerly Kareo) using Excel files. It offers robust data handling, user-friendly file processing, and a production-ready architecture.

---

## Recent Changes (v2.0 Highlights)

> _Note: For a complete list of updates, see the [commit history](https://github.com/saqibcodes007/NPET/commits?per_page=5&sort=author-date&order=desc). This summary may be incomplete due to API limits._

- **Expanded Patient Data Support**
  - Now supports 9 new optional fields in addition to the 5 required ones:
    - Address, City, State, Zip Code, Email Address, Social Security Number (SSN), Medical Record Number (MRN), Mobile Phone, Home Phone

- **Improved File Processing**
  - Flexible column mapping: Accepts various common names for each field (e.g., 'DOB', 'Date of Birth', etc.)
  - Automatic parsing of multiple date formats for DOB (`MM/DD/YYYY`, `MM-DD-YYYY`, etc.)
  - Graceful handling of missing columns or empty cells for optional fields
  - UI instructions updated to reflect new optional columns

- **Production-Ready Improvements**
  - Gunicorn support added for robust multi-user production deployments
  - File download logic and session management refined for stability
  - Temporary file cleanup logic refined to prevent premature deletion

- **Documentation**
  - README and UI documentation updated to reflect new features and field options

---

## Features

- Upload Excel files to create multiple patients at once in Tebra
- Automatic detection of required and optional columns
- Detailed output with results and error messages per patient
- Simple web interface

---

## Getting Started

### Prerequisites

- Python 3.8+
- `pip` (Python package manager)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/saqibcodes007/NPET.git
   cd NPET

2.  **Create and activate a virtual environment (recommended):**

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate

3. **Install dependencies:**

   ```bash
   pip install -r requirements.txt

### Running Locally

1. Set your environment variables for Tebra API credentials (see .env.example for guidance).

2.  Start the Flask development server:

      ```bash
      flask run
      Open your browser and go to http://localhost:5000

### Usage

1.  **Prepare Your Excel File** Create an `.xlsx` file with your patient data. It must contain at least the following required columns:
    * `First Name`
    * `Last Name`
    * `Date of Birth (DOB)`
    * `Gender`
    * `Primary Insurance`

2.  **(Optional) Include Additional Data** You can also include any of the following supported optional columns for more detailed patient profiles:
    * `Address`
    * `City`
    * `State`
    * `Zip Code`
    * `Email`
    * `SSN`
    * `MRN`
    * `Mobile Phone`
    * `Home Phone`

3.  **Upload and Process** Use the web interface to upload your prepared Excel file.

4.  **Download Results** After processing, download the results file, which will contain the status for each patient, including any error details.

## Contributing
Pull requests are welcome! Please open an issue first to discuss your proposed change.

## License
This project is licensed under the MIT License.

---
<p align="center">
  Developed by Saqib Sherwani
  <br>
  Copyright © 2025 • All Rights Reserved
</p>
