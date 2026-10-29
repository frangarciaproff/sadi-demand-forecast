# Forecaster Lambda image (SPEC 7): Python package + Node reader for Access databases.
# Build (from the repository root):
#   docker build --platform linux/amd64 --provenance=false -t sadi-forecaster .
FROM public.ecr.aws/lambda/python:3.12

# Node.js for tools/mdb/supply.mjs (mdb-reader). Amazon Linux 2023 package.
RUN dnf install -y nodejs npm && dnf clean all

COPY tools/mdb/package.json tools/mdb/package-lock.json /opt/mdb/
RUN cd /opt/mdb && npm ci --omit=dev --ignore-scripts
COPY tools/mdb/supply.mjs /opt/mdb/
ENV SADI_MDB_TOOLS=/opt/mdb

# Python dependencies pinned with hashes by uv.lock (exported: make requirements).
COPY infra/forecaster/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt --target "${LAMBDA_TASK_ROOT}"

COPY src/sadi_forecast "${LAMBDA_TASK_ROOT}/sadi_forecast"
COPY infra/forecaster/forecaster_handler.py "${LAMBDA_TASK_ROOT}/"

CMD ["forecaster_handler.handler"]
