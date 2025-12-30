# Eng engil Python talqini
FROM python:3.10-slim

# Ishchi papkani yaratish
WORKDIR /app

# Kutubxonalarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Barcha kodlarni nusxalash
COPY . .

# Botni ishga tushirish
CMD ["python", "main.py"]
