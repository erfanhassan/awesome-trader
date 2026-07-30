import os
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

class DeepSeekClient:
    def __init__(self):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if api_key:
            self.client = AsyncOpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        else:
            self.client = None
            print("WARNING: DEEPSEEK_API_KEY not found in environment.")

    async def get_assessment(self, market_context: dict) -> str:
        if not self.client:
            return "DeepSeek API key not configured."

        prompt = f"""
You are an expert crypto trading analyst. Evaluate the following 1-minute liquidity sweep setup and provide a 2-sentence risk assessment.
Be concise, objective, and highlight any obvious red flags (like contrary HTF trend if applicable, though the system filters for it, or weak volume).

Market Context:
Symbol: {market_context.get('symbol')}
Signal Direction: {market_context.get('direction')}
Current Price: {market_context.get('price')}
Entry: {market_context.get('entry')}
Stop Loss: {market_context.get('sl')}
Take Profit: {market_context.get('tp')}
1D High: {market_context.get('1d_high')}
1D Low: {market_context.get('1d_low')}
4H Trend (20EMA vs 50EMA): {"Bullish" if market_context.get('4h_bullish') else "Bearish"}
1D Trend (20EMA vs 50EMA): {"Bullish" if market_context.get('1d_bullish') else "Bearish"}
Trigger Candle Volume vs Avg: {market_context.get('vol_ratio')}x

Provide a 2-sentence assessment:
"""
        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional trading analyst."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"DeepSeek API Error: {e}")
            return f"Error retrieving AI insight: {e}"
