import json
import os
import uuid

import boto3
import pymysql
from flask import Flask, render_template, request
from werkzeug.utils import secure_filename


app = Flask(__name__)
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
DB_SECRET_ARN = os.environ["DB_SECRET_ARN"]

s3 = boto3.client("s3", region_name=AWS_REGION)
secretsmanager = boto3.client("secretsmanager", region_name=AWS_REGION)


def database_config():
    payload = secretsmanager.get_secret_value(SecretId=DB_SECRET_ARN)
    secret = json.loads(payload["SecretString"])
    return {
        "host": secret["host"],
        "port": int(secret.get("port", 3306)),
        "user": secret["username"],
        "password": secret["password"],
        "database": secret.get("dbname", "studentdb"),
        "connect_timeout": 8,
        "autocommit": True,
    }


def database_connection():
    return pymysql.connect(**database_config())


def ensure_schema():
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS students (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    email VARCHAR(150) NOT NULL,
                    course VARCHAR(100),
                    photo_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/register")
def register():
    name = request.form["name"].strip()
    email = request.form["email"].strip()
    course = request.form["course"].strip()
    photo = request.files["photo"]

    if not name or not email or not course or not photo.filename:
        return "All fields are required", 400

    safe_name = secure_filename(photo.filename)
    object_key = f"uploads/{uuid.uuid4()}-{safe_name}"
    s3.upload_fileobj(
        photo,
        S3_BUCKET_NAME,
        object_key,
        ExtraArgs={"ContentType": photo.mimetype or "application/octet-stream"},
    )
    photo_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET_NAME, "Key": object_key},
        ExpiresIn=3600,
    )

    ensure_schema()
    with database_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO students (name, email, course, photo_url)
                VALUES (%s, %s, %s, %s)""",
                (name, email, course, photo_url),
            )

    return render_template(
        "success.html", name=name, email=email, course=course, photo_url=photo_url
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
