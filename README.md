# Utility API Suite — 7 verified APIs, 1 deployment

All 7 endpoints tested and passing. No image libraries needed, so deployment is lighter and faster.

## The 7 products

| # | Product | Endpoint |
|---|---------|----------|
| 1 | Email Validation API | `GET /v1/email/validate?email=...` |
| 2 | User-Agent Parser API | `GET /v1/useragent/parse?ua=...` |
| 3 | Content Moderation API | `POST /v1/moderation/check` |
| 4 | Password Strength API | `POST /v1/password/strength` |
| 5 | Text Analysis API | `POST /v1/text/analyze` |
| 6 | Unit Converter API | `GET /v1/convert/units?value=100&from=km&to=mi` |
| 7 | Mock Data Generator API | `GET /v1/mock/person?count=5` |

Interactive docs at `/docs` once running.

## Deploy from your phone

1. **GitHub**: github.com → New repository → upload these 3 files
2. **Railway**: railway.app → New Project → Deploy from GitHub repo
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Open `your-url.up.railway.app/docs` and test each endpoint

(Render.com works identically and has a free tier.)

## List on marketplaces

List each endpoint as a separate product on **Zyla API Hub** (zylalabs.com) and **API.market**. They handle billing, API keys, and metering.

Pricing per product:
- Free: 50–100 requests/month
- Basic: $4.99/mo — 5,000 requests
- Pro: $14.99/mo — 50,000 requests
- Ultra: $39.99/mo — 250,000 requests

Best converters to lead with: Email Validation and Content Moderation.
Best free-tier traffic magnets: Mock Data and Unit Converter.
