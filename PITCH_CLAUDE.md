# HomePulse AI — Pitch for Anthropic / Claude AI

---

## The Problem

Every 11 seconds, an older adult is treated in an emergency room for a fall.
Every day, families get that call — the stove was left on, the faucet ran for hours, nobody noticed until it was too late.

There are **54 million Americans over 65**. Most of them want to live independently. Most of their families are terrified to let them.

The current options are bad:
- **Nursing homes** — expensive, isolating, often unwanted
- **Manual check-ins** — inconsistent, intrusive, don't scale
- **Generic smart home devices** — generate false alarms, no real intelligence, no context

Nobody has solved this. Not because the sensors don't exist — they do. Because the intelligence to make sense of them, in real time, with real judgment, didn't exist.

Until Claude.

---

## What We Built

**HomePulse AI** is a real-time home safety system for elderly people living independently.

It combines:
- **Physical Arduino sensors** (temperature, sound, motion, magnetic, pressure) installed in the home
- **A multi-agent AI pipeline** that processes every anomaly end-to-end
- **Computer vision** with Cloudinary that zooms into exactly the right spot in the room
- **Claude** at every reasoning step — triage, analysis, notification writing, weekly health reports

When something happens — the stove is left on at 3am, a faucet has been running for two hours, an unusual sound pattern suggests a fall — the system doesn't just beep. It *thinks*.

---

## Where Claude Lives in This System

Claude isn't a feature. Claude is the brain.

**1. Triage (Claude Sonnet)**
Every anomaly gets sent to Claude with sensor readings, time of day, and deviation score. Claude decides: is this worth waking someone up for? A stove at 47°C at 7pm during dinner is not an emergency. The same reading at 3am when the user is usually asleep is.

Claude returns structured JSON:
```json
{
  "investigate": true,
  "reason": "Temperature 2.8 standard deviations above baseline at 3:17am — atypical for this user's schedule",
  "confidence": 0.91,
  "recommended_action": "Check on stove immediately. User's last detected movement was 4 hours ago."
}
```

**2. Multimodal Reasoning (Claude + Cloudinary Vision)**
When triage flags an event, a webcam captures the scene. Cloudinary crops it to the exact zone (stove, sink, fridge). Claude receives the image URL and reasons about what it sees alongside the sensor data.

**3. Natural Language Notifications**
Claude writes the alert email — not a template. It explains what happened, what the sensor data showed, and what the family member should do. A real sentence, for a real person in a stressful moment.

**4. Weekly Digest**
Every 7 days, Claude reads the week's event history and writes a plain-English safety report to the family: patterns it noticed, changes in behavior, whether thresholds need adjusting.

---

## Why This Hasn't Been Done Before

Most "AI home safety" products are:
- Cloud rules engines with if/then logic
- Single-purpose devices (fall detection only, smoke only)
- No reasoning — just threshold breaches

**HomePulse is the first system to combine:**
- Physical multi-sensor hardware (Arduino, real-world signal capture)
- Orchestrated multi-agent AI (10 specialized agents with distinct roles)
- Claude's contextual reasoning at each decision point
- Computer vision with spatial zone mapping
- Continuous learning from user confirmation feedback

This is not a chatbot. This is an AI that lives in someone's home and watches over them — intelligently, privately, without being intrusive.

---

## The Impact

- **For elderly users**: stay independent longer, in their own home, without surveillance anxiety
- **For families**: peace of mind without constant check-ins — the system calls them when it actually matters
- **For caregivers and healthcare**: early anomaly detection can flag cognitive decline patterns before a crisis
- **For society**: every extra year of independent living saves ~$50,000 in assisted care costs

This isn't a productivity tool. This isn't another chatbot wrapper.

This is Claude helping a 78-year-old woman stay in her own home, safely, with dignity — and letting her daughter sleep at night.

---

## The Stack

| Layer | Technology |
|-------|-----------|
| Sensors | Arduino (temp, sound, magnetic, accel, pressure) |
| Backend | FastAPI + MongoDB (Motor async) |
| Agents | FetchAI uAgents (10 orchestrated agents) |
| AI Reasoning | Anthropic Claude Sonnet (triage, monitor, notify, report) |
| Vision | OpenCV + Cloudinary (capture, crop, enhance) |
| Notifications | Gmail SMTP with Claude-written emails |
| Frontend | React + Vite (live event feed, zone calibrator) |

---

## The Ask

We're not asking for funding. We're asking for recognition that this is what AI should be doing.

Claude isn't being used here to generate tweets or summarize PDFs. It's being used to decide whether an 83-year-old left the stove on, assess the risk, consider the context of their entire week, and communicate clearly to the people who love them.

That's meaningful change. That's what Claude is capable of. And HomePulse AI is proof.
