import asyncio
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.crop_data_cache import CropDataCache

COMMON_CROPS = [
    {
        "crop_key": "wheat",
        "standard_name_en": "Wheat",
        "standard_name_hi": "गेहूँ",
        "about_hi": "गेहूँ भारत की एक प्रमुख रबी फसल है। यह ठंडी जलवायु में अच्छी तरह बढ़ता है। अच्छी पैदावार के लिए समय-समय पर सिंचाई आवश्यक है।",
        "day_stages": {
            "Seedling": 20,
            "Vegetative": 60,
            "Flowering": 90,
            "Ready to Harvest": 130
        },
        "gdd_stages": {
            "Seedling": 300.0,
            "Vegetative": 900.0,
            "Flowering": 1350.0,
            "Ready to Harvest": 1950.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "बीज की बुवाई करें"},
            {"day": 21, "icon": "💧", "task": "पहली सिंचाई (क्राउन रूट इनीसिएशन)"},
            {"day": 45, "icon": "🧪", "task": "यूरिया का छिड़काव करें"},
            {"day": 65, "icon": "💧", "task": "लेट ज्वाइंटिंग पर सिंचाई"},
            {"day": 85, "icon": "🌾", "task": "बालियां निकलने पर सिंचाई"},
            {"day": 130, "icon": "🚜", "task": "फसल की कटाई करें"}
        ]
    },
    {
        "crop_key": "rice",
        "standard_name_en": "Rice",
        "standard_name_hi": "धान",
        "about_hi": "धान एक प्रमुख खरीफ फसल है जिसे बहुत अधिक पानी की आवश्यकता होती है। यह गर्म और नम जलवायु में सबसे अच्छा बढ़ता है।",
        "day_stages": {
            "Seedling": 25,
            "Vegetative": 65,
            "Flowering": 95,
            "Ready to Harvest": 135
        },
        "gdd_stages": {
            "Seedling": 375.0,
            "Vegetative": 975.0,
            "Flowering": 1425.0,
            "Ready to Harvest": 2025.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "नर्सरी में बीज डालें"},
            {"day": 25, "icon": "👨‍🌾", "task": "मुख्य खेत में रोपाई करें"},
            {"day": 30, "icon": "🧪", "task": "पहली खाद डालें"},
            {"day": 50, "icon": "🐛", "task": "कीटनाशक का छिड़काव करें"},
            {"day": 90, "icon": "🌾", "task": "बालियां आने पर पानी बनाए रखें"},
            {"day": 135, "icon": "🚜", "task": "कटाई और मड़ाई करें"}
        ]
    },
    {
        "crop_key": "maize",
        "standard_name_en": "Maize",
        "standard_name_hi": "मक्का",
        "about_hi": "मक्का एक बहुमुखी फसल है जिसे खरीफ और रबी दोनों मौसमों में उगाया जा सकता है। इसे अच्छी जल निकासी वाली मिट्टी चाहिए।",
        "day_stages": {
            "Seedling": 15,
            "Vegetative": 55,
            "Flowering": 75,
            "Ready to Harvest": 110
        },
        "gdd_stages": {
            "Seedling": 225.0,
            "Vegetative": 825.0,
            "Flowering": 1125.0,
            "Ready to Harvest": 1650.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "बीज की बुवाई करें"},
            {"day": 20, "icon": "🧪", "task": "खरपतवार निकालें और खाद डालें"},
            {"day": 40, "icon": "🐛", "task": "फाल आर्मीवर्म के लिए खेत जांचें"},
            {"day": 60, "icon": "💧", "task": "टेसलिंग के समय सिंचाई करें"},
            {"day": 75, "icon": "🌽", "task": "सिल्किंग के समय नमी बनाए रखें"},
            {"day": 110, "icon": "🚜", "task": "भुट्टे सूखने पर कटाई करें"}
        ]
    },
    {
        "crop_key": "cotton",
        "standard_name_en": "Cotton",
        "standard_name_hi": "कपास",
        "about_hi": "कपास एक महत्वपूर्ण नकदी फसल है जिसे लंबी गर्म जलवायु की आवश्यकता होती है। इसे 'सफेद सोना' भी कहा जाता है।",
        "day_stages": {
            "Seedling": 20,
            "Vegetative": 70,
            "Flowering": 100,
            "Ready to Harvest": 150
        },
        "gdd_stages": {
            "Seedling": 300.0,
            "Vegetative": 1050.0,
            "Flowering": 1500.0,
            "Ready to Harvest": 2250.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "बुवाई करें"},
            {"day": 30, "icon": "🧪", "task": "निराई-गुड़ाई और खाद"},
            {"day": 60, "icon": "🐛", "task": "गुलाबी सूंडी के लिए जांच करें"},
            {"day": 90, "icon": "🌺", "task": "फूल आने पर सिंचाई करें"},
            {"day": 120, "icon": "☁️", "task": "टिंडे (bolls) बनने का समय"},
            {"day": 150, "icon": "🧤", "task": "कपास की पहली चुनाई करें"}
        ]
    },
    {
        "crop_key": "tomato",
        "standard_name_en": "Tomato",
        "standard_name_hi": "टमाटर",
        "about_hi": "टमाटर एक प्रमुख सब्जी की फसल है। इसके पौधों को सहारा देने और नियमित सिंचाई की आवश्यकता होती है।",
        "day_stages": {
            "Seedling": 25,
            "Vegetative": 50,
            "Flowering": 70,
            "Ready to Harvest": 100
        },
        "gdd_stages": {
            "Seedling": 375.0,
            "Vegetative": 750.0,
            "Flowering": 1050.0,
            "Ready to Harvest": 1500.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "नर्सरी से खेत में रोपाई करें"},
            {"day": 15, "icon": "🧪", "task": "पहली खाद और निराई"},
            {"day": 35, "icon": "🎋", "task": "पौधों को सहारा (स्टेकिंग) दें"},
            {"day": 55, "icon": "🌺", "task": "फूल आने पर सूक्ष्म पोषक तत्व दें"},
            {"day": 75, "icon": "🐛", "task": "फल छेदक कीट से बचाव करें"},
            {"day": 100, "icon": "🍅", "task": "लाल पके टमाटरों की तुड़ाई करें"}
        ]
    },
    {
        "crop_key": "onion",
        "standard_name_en": "Onion",
        "standard_name_hi": "प्याज",
        "about_hi": "प्याज एक कंद वाली फसल है। अच्छी जल निकासी और सल्फर युक्त मिट्टी इसके तीखेपन और आकार के लिए अच्छी होती है।",
        "day_stages": {
            "Seedling": 40,
            "Vegetative": 70,
            "Flowering": 90,
            "Ready to Harvest": 120
        },
        "gdd_stages": {
            "Seedling": 600.0,
            "Vegetative": 1050.0,
            "Flowering": 1350.0,
            "Ready to Harvest": 1800.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "नर्सरी से रोपाई करें"},
            {"day": 20, "icon": "🧪", "task": "यूरिया और सल्फर डालें"},
            {"day": 45, "icon": "🐛", "task": "थ्रिप्स कीट का नियंत्रण करें"},
            {"day": 70, "icon": "🧅", "task": "कंद (bulb) का विकास शुरू"},
            {"day": 100, "icon": "💧", "task": "सिंचाई बंद कर दें"},
            {"day": 120, "icon": "🚜", "task": "प्याज की खुदाई करें"}
        ]
    },
    {
        "crop_key": "potato",
        "standard_name_en": "Potato",
        "standard_name_hi": "आलू",
        "about_hi": "आलू एक ठंडे मौसम की कंद फसल है। कंदों के अच्छे विकास के लिए मिट्टी का भुरभुरा होना बहुत जरूरी है।",
        "day_stages": {
            "Seedling": 15,
            "Vegetative": 45,
            "Flowering": 65,
            "Ready to Harvest": 100
        },
        "gdd_stages": {
            "Seedling": 225.0,
            "Vegetative": 675.0,
            "Flowering": 975.0,
            "Ready to Harvest": 1500.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🥔", "task": "बीज (कंद) की बुवाई करें"},
            {"day": 25, "icon": "⛏️", "task": "मिट्टी चढ़ाएं (Earthing up)"},
            {"day": 40, "icon": "💧", "task": "नियमित हल्की सिंचाई करें"},
            {"day": 60, "icon": "🍂", "task": "झुलसा रोग (Blight) का उपचार करें"},
            {"day": 85, "icon": "✂️", "task": "ऊपरी पत्ते (haulm) काट दें"},
            {"day": 100, "icon": "🚜", "task": "आलू की खुदाई करें"}
        ]
    },
    {
        "crop_key": "sugarcane",
        "standard_name_en": "Sugarcane",
        "standard_name_hi": "गन्ना",
        "about_hi": "गन्ना एक लंबी अवधि की नकदी फसल है जिसे बहुत अधिक पानी की आवश्यकता होती है। यह भारत की मुख्य व्यावसायिक फसलों में से एक है।",
        "day_stages": {
            "Seedling": 45,
            "Vegetative": 150,
            "Flowering": 250,
            "Ready to Harvest": 365
        },
        "gdd_stages": {
            "Seedling": 675.0,
            "Vegetative": 2250.0,
            "Flowering": 3750.0,
            "Ready to Harvest": 5475.0
        },
        "smart_schedule_hi": [
            {"day": 0, "icon": "🌱", "task": "गन्ने के टुकड़ों की बुवाई करें"},
            {"day": 60, "icon": "💧", "task": "पहली सिंचाई और गुड़ाई"},
            {"day": 120, "icon": "🧪", "task": "यूरिया की टॉप ड्रेसिंग करें"},
            {"day": 180, "icon": "🎋", "task": "गन्ने की बंधाई करें"},
            {"day": 250, "icon": "🐛", "task": "बोरर कीट के लिए निगरानी करें"},
            {"day": 360, "icon": "🚜", "task": "गन्ने की कटाई करें"}
        ]
    }
]

def seed_crops():
    db: Session = SessionLocal()
    try:
        added = 0
        for data in COMMON_CROPS:
            existing = db.query(CropDataCache).filter(CropDataCache.crop_key == data["crop_key"]).first()
            if not existing:
                crop = CropDataCache(**data)
                db.add(crop)
                added += 1
        db.commit()
        print(f"✅ Successfully seeded {added} common crops in Hindi.")
    except Exception as e:
        print(f"❌ Error seeding crops: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    print("Seeding database with common Indian crops (Hindi)...")
    seed_crops()
