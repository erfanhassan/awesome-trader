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
            
    async def generate_mentor_review(self, trade_data: dict) -> str:
        if not self.client:
            return "DeepSeek API key not configured."
            
        timeline = trade_data.get("timeline_events", [])
        timeline_str = "\n".join([f"- {event['timestamp']}: {event['message']}" for event in timeline])
        
        prompt = f"""
You are an expert crypto trading mentor. Review the following closed trade and provide a 1-paragraph summary grading the trade and explaining the outcome to the user.
Give it a grade (A to F) based on risk management and outcome. Discuss if the margin additions (if any) were dangerous or justified.

Trade Summary:
Symbol: {trade_data.get('symbol')}
Direction: {trade_data.get('direction')}
Entry: {trade_data.get('entry')}
Exit: {trade_data.get('exit_price')}
Net PnL: ${trade_data.get('net_profit', 0):.2f}
Close Reason: {trade_data.get('close_reason')}

Live Timeline Feed:
{timeline_str}

Provide a comprehensive, conversational paragraph (around 4-6 sentences) speaking directly to the user as their trading mentor.
"""
        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional and witty crypto trading mentor."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=250
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"DeepSeek API Error: {e}")
            return f"Error retrieving Mentor Review: {e}"

    async def generate_hourly_report(self, market_context: dict) -> str:
        if not self.client:
            return "DeepSeek API key not configured."
            
        prompt = f"""
You are the AI brain behind an automated crypto trading bot. Your job is to reduce the user's FOMO by explaining exactly why the bot stayed out of the market for the last hour.

Market Context Passed from Trading Engine:
Symbol: {market_context.get('symbol')}
Market Regime (1H Trend): {market_context.get('regime')}
ADX Strength: {market_context.get('adx')} (Under 25 is sideways/choppy, Over 25 is trending)
Liquidity Sweeps Detected: {market_context.get('sweeps_count')}
Trades Taken: 0

Based on this data, write a 1-2 sentence explanation speaking directly to the user. Explain how the bot successfully protected their capital by not forcing a trade in these conditions. Be concise, professional, and reassuring.
"""
        try:
            response = await self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional, transparent crypto trading AI."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=150
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"DeepSeek API Error: {e}")
            return f"Error generating hourly report: {e}"

