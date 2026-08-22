# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ .
RUN npm run build

# Stage 2: Build the Python backend and serve everything
FROM python:3.9-slim
WORKDIR /app/backend

# Install python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend/ .

# Copy built frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Expose port (Cloud Run sets PORT env var)
ENV PORT 8080
EXPOSE 8080

# Command to run the application
CMD ["python", "main.py"]
