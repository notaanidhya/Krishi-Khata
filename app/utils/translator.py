import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from deep_translator import GoogleTranslator
from app.models.translation import TranslationCache

logger = logging.getLogger(__name__)

def translate_to_hindi(texts: List[str], db: Session) -> Dict[str, str]:
    """
    Translates a list of strings to Hindi.
    Checks the database cache first to avoid rate limiting and speed up responses.
    Saves new translations to the database.
    """
    if not texts:
        return {}

    # Deduplicate input
    unique_texts = list(set([t.strip() for t in texts if t and t.strip()]))
    if not unique_texts:
        return {}

    result = {}
    missing_texts = []

    # 1. Fetch existing translations from DB
    try:
        cached = db.query(TranslationCache).filter(
            TranslationCache.original_text.in_(unique_texts),
            TranslationCache.lang_code == "hi"
        ).all()
        
        cached_map = {item.original_text: item.translated_text for item in cached}
        
        for text in unique_texts:
            if text in cached_map:
                result[text] = cached_map[text]
            else:
                missing_texts.append(text)
    except Exception as e:
        logger.error(f"Error querying translation cache: {e}")
        missing_texts = unique_texts

    # 2. Translate missing texts
    if missing_texts:
        import concurrent.futures

        def _do_translate(text):
            try:
                translator = GoogleTranslator(source='en', target='hi')
                return text, translator.translate(text)
            except Exception as e:
                logger.warning(f"Failed to translate '{text}': {e}")
                return text, text

        try:
            new_cache_entries = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                # Map translations concurrently
                future_to_text = {executor.submit(_do_translate, text): text for text in missing_texts}
                for future in concurrent.futures.as_completed(future_to_text):
                    text, translated = future.result()
                    if translated:
                        result[text] = translated
                        if translated != text:
                            new_cache_entries.append(
                                TranslationCache(
                                    original_text=text,
                                    lang_code="hi",
                                    translated_text=translated
                                )
                            )
                    else:
                        result[text] = text # fallback to original if empty

            # 3. Save new translations to DB
            if new_cache_entries:
                db.bulk_save_objects(new_cache_entries)
                db.commit()

        except Exception as e:
            logger.error(f"Translation service error: {e}")
            db.rollback()
            # Fallback to original text for missing
            for text in missing_texts:
                if text not in result:
                    result[text] = text

    return result
