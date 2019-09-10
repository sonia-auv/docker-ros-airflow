"""
 This DAG will upload image to google cloud storage dataset
"""

import logging
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash_operator import BashOperator
from airflow.operators.python_operator import PythonOperator, BranchPythonOperator
from airflow.contrib.sensors.file_sensor import FileSensor
from airflow.operators.slack_operator import SlackAPIPostOperator
from airflow.models import Variable
from airflow.hooks.base_hook import BaseHook
from airflow.contrib.operators.slack_webhook_operator import SlackWebhookOperator

from export_img_to_gcs_dataset import export_img_to_gcs_dataset

ROOT_FOLDER = "/usr/local/airflow/data/"
IMAGE_FOLDER = os.path.join(ROOT_FOLDER, "images")
CSV_FOLDER = os.path.join(ROOT_FOLDER, "csv")
BASE_URL = "https://storage.cloud.google.com/"
slack_webhook_token = BaseHook.get_connection('slack').password

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2019, 1, 24),
    "email": ["club.sonia@etsmtl.net"],
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,
}


with DAG("export_images_to_gcs_dataset", catchup=False, default_args=default_args) as dag:

    logging.info("Starting images export to google cloud storage")

    storage_name = Variable.get("Bucket")
    dataset = Variable.get("Dataset")

    # Build GCS path
    gcs_images_path = BASE_URL + os.path.join(storage_name, dataset)

    input_location = os.path.join(IMAGE_FOLDER, dataset)
    output_location = "gs://" + os.path.join(storage_name, dataset)

    task_notify_start = SlackWebhookOperator(
        task_id="task_notify_start",
        http_conn_id='slack',
        webhook_token=slack_webhook_token,
        username='airflow',
        message=" :dolphin:[PROCESSING] DAG (export_img_to_gcs_dataset): Exporting image to GCP dataset folder",
        dag=dag,
    )

    command = "gsutil -m cp -r {src_folder} {dest_bucket}".format(
        src_folder=input_location, dest_bucket=output_location
    )
    task_export_images_to_gcs_dataset = BashOperator(
        task_id="task_export_images_to_gcs_dataset", bash_command=command, dag=dag
    )

    task_create_csv = PythonOperator(
        task_id="task_create_csv",
        python_callable=export_img_to_gcs_dataset.create_csv,
        op_kwargs={
            "images_path": IMAGE_FOLDER, 
            "dataset": dataset,
            "gcs_images_path": gcs_images_path,
            "csv_path": CSV_FOLDER
        },
        dag=dag,
    )

    task_notify_export_success = SlackWebhookOperator(
        task_id="task_notify_export_to_gcs_success",
        http_conn_id='slack',
        webhook_token=slack_webhook_token,
        username='airflow',
        message=":heavy_check_mark: [SUCCESS] DAG (export_img_to_gcs_dataset): Images were exported to google cloud storage",
        trigger_rule="all_success",
        dag=dag,
    )

    task_notify_export_failure = SlackWebhookOperator(
        task_id="task_notify_export_to_gcs_failure",
        http_conn_id='slack',
        webhook_token=slack_webhook_token,
        username='airflow',
        message=":heavy_multiplication_x: [FAILURE] DAG (export_img_to_gcs_dataset): There was an error while exporting image to google cloud storage",
        trigger_rule="one_failed",
        dag=dag,
    )

    task_notify_start.set_downstream(task_export_images_to_gcs_dataset)
    task_export_images_to_gcs_dataset.set_downstream(task_create_csv)
    task_create_csv.set_downstream(task_notify_export_success)
    task_create_csv.set_downstream(task_notify_export_failure)
