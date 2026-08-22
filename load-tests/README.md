# Load testing

Run the API with a production-like database and use k6, Locust, or another approved tool against `/api/dashboard` and `/api/requests`.

Suggested stages: 100, 500, and 1,000 concurrent users. Capture requests per second, average and p95 response time, and error rate. Capacity depends on CPU, RAM, database resources, network, and scaling configuration; this project makes no guaranteed capacity claim.
