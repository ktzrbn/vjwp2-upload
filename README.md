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

### 3. Fill out `.env`

Edit the `.env` file in the project root:

```dotenv
S3_BUCKET=your-bucket-name
AWS_REGION=us-east-1
# These credentials are for the upload web app, not for SSH server access.
BASIC_USER=admin
BASIC_PASSWORD=change-this-password
S3_PDF_PREFIX=pdfs
S3_SMALL_PREFIX=smalls
S3_THUMB_PREFIX=thumbnails
HOST=127.0.0.1
PORT=8000
RELOAD=false
```

Notes:

- `HOST=127.0.0.1` is the right default when nginx is reverse proxying this app on the same server.
- Change `PORT` only if `8000` is already in use.
- Set `RELOAD=true` only for local development.
- `BASIC_USER` and `BASIC_PASSWORD` protect the upload page in the browser. They are not your Linux login credentials.
- Recreate this same `.env` file on the server; it is intentionally gitignored.

### 4. Run

```bash
source .venv/bin/activate
python main.py
```

For development, change `RELOAD=true` in `.env`.

### 5. Run as a systemd service

Create `/etc/systemd/system/vjwp.service`:

```ini
[Unit]
Description=VJWP PDF Processor
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/vjwp2-uploads
EnvironmentFile=/home/ec2-user/vjwp2-uploads/.env
ExecStart=/home/ec2-user/vjwp2-uploads/.venv/bin/uvicorn main:app --host ${HOST} --port ${PORT}
Restart=always

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vjwp
```

Your server copy of `.env` must use `KEY=VALUE` format with no `export` keyword.

### 6. Put the app behind nginx on a subdomain

If the server already hosts another nginx site, keep that existing site in place and add a new server block for `objectupload.vjwp.org`.

1. Create a DNS record for `objectupload.vjwp.org` pointing to the server.
2. SSH into the server with your PEM key, for example:

```bash
ssh -i your-key.pem ec2-user@<your-instance-ip>
```

3. Make sure the FastAPI service is running locally on `127.0.0.1:8000`.
4. Create `/etc/nginx/conf.d/objectupload.vjwp.org.conf`:

```nginx
server {
	listen 80;
	server_name objectupload.vjwp.org;

	client_max_body_size 100M;

	location / {
		proxy_pass http://127.0.0.1:8000;
		proxy_http_version 1.1;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}
```

5. Test and reload nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

6. Add TLS with Certbot once DNS is live:

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d objectupload.vjwp.org
```

After that, the web UI for this app will be available at `https://objectupload.vjwp.org/` while your existing nginx-hosted site can remain on its current domain or subdomain.

## AWS Credentials

Your PEM key (e.g. `your-key.pem`) is used to **SSH into the EC2 instance only**. It is not used for S3 access, and it is not the same thing as the app's `BASIC_PASSWORD`.

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
- The upload endpoint is protected by HTTP Basic Auth. Use HTTPS in production.
