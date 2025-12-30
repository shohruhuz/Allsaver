FROM python:3.10-slim

# Tizimga FFmpeg o'rnatish
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

WORKDIR /app

# Kutubxonalarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Barcha fayllarni nusxalash
COPY . .

# Botni ishga tushirish
CMD ["python", "main.py"]
