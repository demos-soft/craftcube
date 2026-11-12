FROM docker.io/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# sqlite data dir (mounted volume in compose)
ENV CRAFTCUBE_DB=/data/craftcube.sqlite
RUN mkdir -p /data

EXPOSE 8000
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "2", "-t", "120", "run:app"]
