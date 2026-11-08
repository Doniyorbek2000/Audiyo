-- Tizim ovozlari (user_id = NULL). ElevenLabs roʻyxatini /api/v1/voices/sync bilan yangilash mumkin.
INSERT INTO voice_profiles (user_id, name, provider, provider_voice_id, gender, age_group, is_narrator, description) VALUES
  -- Google Gemini TTS (prebuilt)
  (NULL, 'Charon (hikoyachi)', 'gemini', 'Charon', 'MALE', 'ADULT', TRUE, 'Informativ, neytral erkak ovozi'),
  (NULL, 'Kore (hikoyachi)', 'gemini', 'Kore', 'FEMALE', 'ADULT', TRUE, 'Qatʼiy, aniq ayol ovozi'),
  (NULL, 'Puck', 'gemini', 'Puck', 'MALE', 'YOUNG_ADULT', FALSE, 'Shoʻx, yosh erkak'),
  (NULL, 'Fenrir', 'gemini', 'Fenrir', 'MALE', 'ADULT', FALSE, 'Hayajonli erkak'),
  (NULL, 'Orus', 'gemini', 'Orus', 'MALE', 'ADULT', FALSE, 'Mustahkam erkak'),
  (NULL, 'Iapetus', 'gemini', 'Iapetus', 'MALE', 'ELDERLY', FALSE, 'Tiniq, yoshi kattaroq erkak'),
  (NULL, 'Algenib', 'gemini', 'Algenib', 'MALE', 'ELDERLY', FALSE, 'Xirildoq, keksa erkak'),
  (NULL, 'Enceladus', 'gemini', 'Enceladus', 'MALE', 'YOUNG_ADULT', FALSE, 'Nafasli, yumshoq erkak'),
  (NULL, 'Leda', 'gemini', 'Leda', 'FEMALE', 'YOUNG_ADULT', FALSE, 'Yosh ayol'),
  (NULL, 'Aoede', 'gemini', 'Aoede', 'FEMALE', 'ADULT', FALSE, 'Yengil ayol ovozi'),
  (NULL, 'Zephyr', 'gemini', 'Zephyr', 'FEMALE', 'YOUNG_ADULT', FALSE, 'Yorqin ayol'),
  (NULL, 'Gacrux', 'gemini', 'Gacrux', 'FEMALE', 'ELDERLY', FALSE, 'Yetuk ayol'),
  (NULL, 'Laomedeia', 'gemini', 'Laomedeia', 'FEMALE', 'CHILD', FALSE, 'Shoʻx, bolalarcha'),
  (NULL, 'Achird', 'gemini', 'Achird', 'MALE', 'CHILD', FALSE, 'Doʻstona, yosh'),
  -- ElevenLabs (premade)
  (NULL, 'Adam', 'elevenlabs', 'pNInz6obpgDQGcFmaJgB', 'MALE', 'ADULT', FALSE, 'Chuqur erkak'),
  (NULL, 'Antoni', 'elevenlabs', 'ErXwobaYiN019PkySvjV', 'MALE', 'YOUNG_ADULT', FALSE, 'Yumshoq erkak'),
  (NULL, 'Josh', 'elevenlabs', 'TxGEqnHWrfWFTfGW9XjX', 'MALE', 'YOUNG_ADULT', FALSE, 'Yosh erkak'),
  (NULL, 'Arnold', 'elevenlabs', 'VR6AewLTigWG4xSOukaG', 'MALE', 'ELDERLY', FALSE, 'Xirildoq erkak'),
  (NULL, 'Rachel', 'elevenlabs', '21m00Tcm4TlvDq8ikWAM', 'FEMALE', 'ADULT', FALSE, 'Sokin ayol'),
  (NULL, 'Sarah', 'elevenlabs', 'EXAVITQu4vr4xnSDxMaL', 'FEMALE', 'YOUNG_ADULT', FALSE, 'Yumshoq ayol'),
  (NULL, 'Domi', 'elevenlabs', 'AZnzlk1XvdvUeBnXmlld', 'FEMALE', 'YOUNG_ADULT', FALSE, 'Kuchli ayol'),
  (NULL, 'Elli', 'elevenlabs', 'MF3mGyEYCl7XYWbV9V6O', 'FEMALE', 'CHILD', FALSE, 'Yosh, emotsional')
ON CONFLICT DO NOTHING;
