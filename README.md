# S3 File Extension Renamer

This is a simple Flask web application that allows you to rename file extensions in an AWS S3 bucket. You can preview the changes before applying them, and you can choose whether to keep or delete the original files.

## Features

-   Connect to any AWS S3 bucket with your credentials.
-   List files with a specific extension in a given prefix (folder).
-   Recursively scan for files in sub-prefixes.
-   Preview the files that will be renamed.
-   Select which files to rename.
-   Choose to keep or delete the original files.
-   Logging of all operations to `app.log` and the console.

## Setup

1.  **Clone the repository:**

    ```bash
    git clone <your-repository-url>
    cd <your-repository-directory>
    ```

2.  **Create a virtual environment:**

    It's recommended to use a virtual environment to manage dependencies.

    ```bash
    python -m venv venv
    ```

3.  **Activate the virtual environment:**

    -   On Windows:
        ```bash
        venv\Scripts\activate
        ```
    -   On macOS and Linux:
        ```bash
        source venv/bin/activate
        ```

4.  **Install the required packages:**

    ```bash
    pip install -r requirements.txt
    ```

## Usage

1.  **Run the Flask application:**

    ```bash
    python s3bucket_ext_rename.py
    ```

2.  **Open your web browser** and navigate to `http://127.0.0.1:5000`.

3.  **Enter your AWS credentials:**
    -   AWS Access Key ID
    -   AWS Secret Access Key
    -   S3 Bucket Name

4.  **Specify the files to rename:**
    -   **Prefix (Optional):** The folder path to search in. Leave blank to search from the root of the bucket.
    -   **Old Extension:** The file extension you want to change (e.g., `.txt`).
    -   **New Extension:** The new file extension (e.g., `.log`).

5.  **Choose your options:**
    -   **Recursive:** Check this to include files in sub-folders.
    -   **Keep Original:** Check this to keep the original files after renaming. If unchecked, the original files will be deleted.

6.  **Preview and Confirm:**
    -   Click **Preview** to see a list of files that will be affected.
    -   Select the files you want to rename.
    -   Click **Confirm Renaming** to apply the changes.

7.  **View the results:**
    -   A results page will show the outcome of the operation, including any errors.

## Logging

All actions are logged to `app.log` in the project's root directory and are also printed to the console. This is useful for debugging and tracking the application's activity. 