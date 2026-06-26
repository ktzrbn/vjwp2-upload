import os
import re
import shutil
import boto3
from botocore.exceptions import NoCredentialsError, PartialCredentialsError
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pdf2image import convert_from_bytes
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
security = HTTPBasic()

# ====== CONFIGURATION ======
S3_BUCKET = os.environ.get("S3_BUCKET", "victorianjewishwritersproject")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BASIC_USER = os.environ.get("BASIC_USER", "admin")
BASIC_PASSWORD = os.environ.get("BASIC_PASSWORD", "supersecretpassword")
USER_DB = {BASIC_USER: BASIC_PASSWORD}

def normalize_prefix(prefix: str) -> str:
    return prefix.strip().strip("/")


S3_PDF_PREFIX = normalize_prefix(os.environ.get("S3_PDF_PREFIX", "objects"))
S3_SMALL_PREFIX = normalize_prefix(os.environ.get("S3_SMALL_PREFIX", "objects/small"))
S3_THUMB_PREFIX = normalize_prefix(os.environ.get("S3_THUMB_PREFIX", "objects/thumbs"))
POPPLER_PATH = os.environ.get("POPPLER_PATH") or None

# Standard CollectionBuilder bounding boxes
SMALL_SIZE = (800, 800)
THUMB_SIZE = (300, 300)  # Change to (450, 450) if your specific theme uses the 450px variation

# Initialize S3 client with region
s3_client = boto3.client('s3', region_name=AWS_REGION)


def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = USER_DB.get(credentials.username)
    if not correct_username or credentials.password != correct_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def build_s3_key(prefix: str, filename: str) -> str:
    return f"{prefix}/{filename}" if prefix else filename


@app.get("/", response_class=HTMLResponse)
async def main_page(username: str = Depends(get_current_username)):
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>VJWP PDF Portal</title></head>
    <body style="font-family: Arial, sans-serif; margin: 40px;">
        <h2>VJWP Document Processor (CollectionBuilder Spec)</h2>
        <p>Logged in as: <b>{username}</b></p>
        <form action="/upload" method="post" enctype="multipart/form-data" style="background: #f4f4f4; padding: 20px; border-radius: 8px; max-width: 400px;">
            <label><b>VJWP Identifier (Object ID):</b></label><br>
            <input type="text" name="vjwp_id" required placeholder="e.g. vjwp_123" pattern="vjwp_[0-9]+" style="width:100%; margin-bottom:15px; padding:8px;"><br>
            
            <label><b>Select PDF:</b></label><br>
            <input type="file" name="file" accept=".pdf" required style="margin-bottom:20px;"><br>
            
            <button type="submit" style="background:#007BFF; color:white; border:none; padding:10px 15px; cursor:pointer; border-radius:4px;">Upload & Process</button>
        </form>
    </body>
    </html>
    """


@app.post("/upload", response_class=HTMLResponse)
async def handle_upload(
    vjwp_id: str = Form(...), 
    file: UploadFile = File(...),
    username: str = Depends(get_current_username)
):
    vjwp_id = vjwp_id.strip().lower()
    if not re.fullmatch(r"vjwp_\d+", vjwp_id):
        raise HTTPException(status_code=400, detail="Invalid VJWP identifier. Use the format vjwp_<number>.")
    
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    
    try:
        poppler_path = POPPLER_PATH
        if not poppler_path and not shutil.which("pdfinfo"):
            raise Exception(
                "Poppler is not available. Install Poppler and either add it to PATH or set POPPLER_PATH in .env."
            )

        # Replicate CollectionBuilder PDF rendering: Render page 1 at 300 DPI density using Poppler
        images = convert_from_bytes(
            pdf_bytes,
            first_page=1,
            last_page=1,
            dpi=300,
            poppler_path=poppler_path,
        )
        if not images:
            raise Exception("Poppler failed to extract any pages from this PDF.")
        
        first_page_image = images[0]
        
        # Ensure image is in RGB format (required for saving as JPEG if PDF was CMYK)
        if first_page_image.mode != 'RGB':
            first_page_image = first_page_image.convert('RGB')
            
        # --- 1. Create Small Image (_sm.jpg) ---
        small_img = first_page_image.copy()
        small_img.thumbnail(SMALL_SIZE, Image.Resampling.LANCZOS)
        small_io = BytesIO()
        small_img.save(small_io, format="JPEG", quality=85, optimize=True)
        small_bytes = small_io.getvalue()
        
        # --- 2. Create Thumbnail Image (_th.jpg) ---
        thumb_img = first_page_image.copy()
        thumb_img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
        thumb_io = BytesIO()
        thumb_img.save(thumb_io, format="JPEG", quality=80, optimize=True)
        thumb_bytes = thumb_io.getvalue()

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Image processing failed: {str(e)}")

    # Match CollectionBuilder exact structural folders and extensions
    orig_key = build_s3_key(S3_PDF_PREFIX, f"{vjwp_id}.pdf")
    small_key = build_s3_key(S3_SMALL_PREFIX, f"{vjwp_id}_sm.jpg")
    thumb_key = build_s3_key(S3_THUMB_PREFIX, f"{vjwp_id}_th.jpg")

    # Push to S3 with correct Mime-Types
    try:
        s3_client.put_object(Bucket=S3_BUCKET, Key=orig_key, Body=pdf_bytes, ContentType="application/pdf")
        s3_client.put_object(Bucket=S3_BUCKET, Key=small_key, Body=small_bytes, ContentType="image/jpeg")
        s3_client.put_object(Bucket=S3_BUCKET, Key=thumb_key, Body=thumb_bytes, ContentType="image/jpeg")
    except (NoCredentialsError, PartialCredentialsError):
        raise HTTPException(
            status_code=500,
            detail="Failed to upload to S3: no AWS credentials found. For local testing, set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env, or use an AWS profile. On EC2, attach an IAM role to the instance.",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to S3: {str(e)}")

    # Generate Public Links
    base_url = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com"
    orig_url = f"{base_url}/{orig_key}"
    small_url = f"{base_url}/{small_key}"
    thumb_url = f"{base_url}/{thumb_key}"

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Upload Success</title></head>
    <body style="font-family: Arial, sans-serif; margin: 40px;">
        <h2 style="color: green;">✓ Replicated CollectionBuilder Derivatives Successfully!</h2>
        <p>Copy your public links below:</p>
        
        <div style="margin-bottom: 15px;">
            <label><b>Original PDF (object_location):</b></label><br>
            <input type="text" value="{orig_url}" readonly style="width: 80%; padding: 8px;" onclick="this.select()">
        </div>
        
        <div style="margin-bottom: 15px;">
            <label><b>Small Image (image_small):</b></label><br>
            <input type="text" value="{small_url}" readonly style="width: 80%; padding: 8px;" onclick="this.select()">
        </div>
        
        <div style="margin-bottom: 15px;">
            <label><b>Thumbnail Image (image_thumb):</b></label><br>
            <input type="text" value="{thumb_url}" readonly style="width: 80%; padding: 8px;" onclick="this.select()">
        </div>
        
        <br>
        <a href="/" style="text-decoration: none; background: #333; color: white; padding: 10px 15px; border-radius: 4px;">Upload Another File</a>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    reload_enabled = os.environ.get("RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload_enabled)
