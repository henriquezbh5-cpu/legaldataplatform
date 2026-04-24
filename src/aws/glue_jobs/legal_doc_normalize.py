"""AWS Glue job (PySpark) — normalize Bronze → Silver for legal documents.

This is the heavy-weight path for when data volumes exceed what a single
Python process can handle. Glue runs PySpark at the scale of terabytes with
no cluster management.

Deployment: sync this file to S3 and reference it from a Glue job definition
(see infra/terraform/glue.tf).
"""

import sys

from awsglue.context import GlueContext  # type: ignore
from awsglue.job import Job  # type: ignore
from awsglue.utils import getResolvedOptions  # type: ignore
from pyspark.context import SparkContext
from pyspark.sql import functions as F  # noqa: N812  (PySpark convention)


def main() -> None:
    args = getResolvedOptions(
        sys.argv,
        [
            "JOB_NAME",
            "source_bucket",
            "target_bucket",
            "ingestion_date",
        ],
    )

    sc = SparkContext()
    glue = GlueContext(sc)
    spark = glue.spark_session
    job = Job(glue)
    job.init(args["JOB_NAME"], args)

    source_path = (
        f"s3://{args['source_bucket']}/legal_documents/ingestion_date={args['ingestion_date']}/"
    )
    target_path = f"s3://{args['target_bucket']}/legal_documents/"

    df = spark.read.parquet(source_path)

    # Normalization
    normalized = (
        df.withColumn("title", F.trim(F.upper(F.col("title"))))
        .withColumn("document_type", F.upper(F.col("document_type")))
        .withColumn("jurisdiction", F.trim(F.col("jurisdiction")))
        .withColumn(
            "source_hash",
            F.sha2(
                F.concat_ws("|", "source_system", "source_id", "document_date"),
                256,
            ),
        )
        .dropDuplicates(["source_hash"])
    )

    (normalized.write.mode("append").partitionBy("document_date").parquet(target_path))

    job.commit()


if __name__ == "__main__":
    main()
