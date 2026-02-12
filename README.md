# Crear el entorno virtual de Python.
python -m venv .venv

# Activar el entorno virtual.
.venv\Scripts\Activate

# Instalar las dependencias, esto solo se hace la primera vez.
pip install -r requirements.txt

# Prender la aplicacion con el hot reload para ver los cambios en directo.
uvicorn main:app --reload