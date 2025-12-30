# Python asosiy imidji
FROM python:3.10-slim

# Kerakli tizim paketlarini o'rnatish (ffmpeg, git, curl, build-essential)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        build-essential \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Ishchi katalog
WORKDIR /app

# Talablarni o'rnatish uchun requirements.txt ni nusxalash
COPY requirements.txt .

# Python talablarini o'rnatish
RUN pip install --no-cache-dir -r requirements.txt

# Kodni nusxalash
COPY . .

# Downloads katalogini yaratish (agar kerak bo'lsa)
RUN mkdir -p downloads

# Botni ishga tushirish
CMD ["python", "main.py"]
