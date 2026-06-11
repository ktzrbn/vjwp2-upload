# VJWP PDF Processor

FastAPI service that accepts a PDF upload, renders the first page to JPEG using Poppler, generates a small image and thumbnail sized to CollectionBuilder spec, and uploads both to S3.

## Quick Start (AlmaLinux / Amazon Linux)

### 1. Install system dependencies

**AlmaLinux 8/9 or Amazon Linux 2023:**
```bash
sudo dnf install -y poppler-utils python3 python3-pip python3-venv
```

**Amazon Linux 2 (older):**
```bash
sudo amazon-linux-extras enable python3.8   # if needed
sudo yum install -y poppler-utils python3 python3-pip
```

### 2. Create a virtualenv and install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Set environment variables

```bash
export S3_BUCKET=your-bucket-name
export AWS_REGION=us-east-1
export BASIC_USER=admin
export BASIC_PASSWORD=supersecretpassword

# S3 folder layout (defaults match CollectionBuilder conventions)
export S3_PDF_PREFIX=pdfs
export S3_SMALL_PREFIX=smalls
export S3_THUMB_PREFIX=thumbnails
```

### 4. Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Add `--reload` during development. Remove it in production.

### 5. (Optional) Run as a systemd service

Create `/etc/systemd/system/vjwp.service`:

```ini
[Unit]
Description=VJWP PDF Processor
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/vjwp2-uploads
EnvironmentFile=/home/ec2-user/vjwp2-uploads/.env
ExecStart=/home/ec2-user/vjwp2-uploads/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vjwp
```

Put your `export` statements in `/home/ec2-user/vjwp2-uploads/.env` using `KEY=VALUE` format (no `export` keyword) when using `EnvironmentFile`.

## AWS Credentials

Your PEM key (e.g. `your-key.pem`) is used to **SSH into the EC2 instance only** — it is not used for S3 access.

S3 access is handled separately via the EC2 instance's **IAM role**:

1. In the AWS Console, create an IAM role with the `AmazonS3FullAccess` policy (or a scoped-down policy granting at minimum `s3:PutObject` on your bucket).
2. Attach that role to your EC2 instance under **Actions → Security → Modify IAM role**.
3. boto3 will automatically use the instance role — no access keys or credential files needed.

To SSH into the instance and deploy:

```bash
ssh -i your-key.pem ec2-user@<your-instance-ip>
```

## Notes

- Poppler renders PDF page 1 at 300 DPI before resizing — same pipeline as CollectionBuilder.
- Small image: 800×800 px max, JPEG quality 85.
- Thumbnail: 300×300 px max, JPEG quality 80 (change `THUMB_SIZE` in `main.py` to `(450, 450)` if your CollectionBuilder theme requires it).
- The upload endpoint is protected by HTTP Basic Auth. Use HTTPS (e.g. behind an nginx reverse proxy with a TLS cert) in production.
