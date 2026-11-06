# Dockerfile
FROM apache/airflow:3.1.0-python3.12

# Cambiar a usuario root para instalar paquetes del sistema si se requiere
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt-get/lists/*

# Regresar al usuario airflow para instalar librerías de Python
USER airflow

# Copiar requirements.txt
COPY requirements.txt /requirements.txt

# Instalar dependencias respetando la versión base de Airflow 3.1.0
RUN pip install --no-cache-dir -r /requirements.txt

# Copiar directorios del proyecto al contenedor
COPY --chown=airflow:root config/ /opt/airflow/config/
COPY --chown=airflow:root plugins/ /opt/airflow/plugins/
COPY --chown=airflow:root sql/ /opt/airflow/sql/
COPY --chown=airflow:root scripts/ /opt/airflow/scripts/