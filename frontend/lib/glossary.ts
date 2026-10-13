// Frontend glossary for tap-to-explain (F12). Starter set so the UI works today.
// TODO(A15): when backend/app/data/glossary.json (40-50 terms, checked by a Hindi/Marathi speaker)
// is ready, replace this list with it (same shape) - nothing else needs to change.
import type { Lang } from './types';

export interface GlossaryEntry {
  id: string;
  /** English spellings to find in policy text (case-insensitive). */
  match: string[];
  term: Record<Lang, string>;
  meaning: Record<Lang, string>;
}

export const GLOSSARY: GlossaryEntry[] = [
  {
    id: 'copay',
    match: ['co-payment', 'co-pay', 'copay'],
    term: { en: 'Co-pay', hi: 'को-पे', mr: 'को-पे' },
    meaning: {
      en: 'The share of every hospital bill that you pay yourself. The insurer pays the rest.',
      hi: 'हर अस्पताल बिल का वह हिस्सा जो आप खुद भरते हैं। बाकी बीमा कंपनी भरती है।',
      mr: 'प्रत्येक रुग्णालय बिलाचा जो भाग तुम्ही स्वतः भरता. उर्वरित विमा कंपनी भरते.',
    },
  },
  {
    id: 'sublimit',
    match: ['sub-limits', 'sub-limit', 'sublimit', 'sub limit'],
    term: { en: 'Sub-limit', hi: 'सब-लिमिट', mr: 'सब-लिमिट' },
    meaning: {
      en: 'A smaller cap for one item (for example cataract surgery), even when your total cover is bigger.',
      hi: 'किसी एक चीज़ (जैसे मोतियाबिंद ऑपरेशन) की छोटी सीमा, भले ही आपका कुल कवर ज़्यादा हो।',
      mr: 'एखाद्या गोष्टीसाठी (उदा. मोतीबिंदू शस्त्रक्रिया) लहान मर्यादा, एकूण कव्हर जास्त असले तरीही.',
    },
  },
  {
    id: 'waiting',
    match: ['waiting periods', 'waiting period'],
    term: { en: 'Waiting period', hi: 'प्रतीक्षा अवधि', mr: 'प्रतीक्षा कालावधी' },
    meaning: {
      en: 'Time after buying the policy during which you cannot claim for certain illnesses.',
      hi: 'पॉलिसी लेने के बाद का वह समय जब आप कुछ बीमारियों के लिए क्लेम नहीं कर सकते।',
      mr: 'पॉलिसी घेतल्यानंतरचा तो काळ ज्यात काही आजारांसाठी क्लेम करता येत नाही.',
    },
  },
  {
    id: 'roomrent',
    match: ['room rent', 'room-rent'],
    term: { en: 'Room rent limit', hi: 'कमरे के किराये की सीमा', mr: 'खोली भाड्याची मर्यादा' },
    meaning: {
      en: 'The most the insurer allows per day for your hospital room. A costlier room can reduce the whole claim.',
      hi: 'अस्पताल के कमरे के लिए बीमा कंपनी रोज़ जितना देती है, उसकी अधिकतम सीमा। महँगा कमरा पूरा क्लेम घटा सकता है।',
      mr: 'रुग्णालयातील खोलीसाठी विमा कंपनी दिवसाला जास्तीत जास्त जितके देते ती मर्यादा. महागडी खोली संपूर्ण क्लेम कमी करू शकते.',
    },
  },
  {
    id: 'suminsured',
    match: ['sum insured'],
    term: { en: 'Sum insured', hi: 'बीमा राशि', mr: 'विमा रक्कम' },
    meaning: {
      en: 'The most the insurer will pay in one policy year.',
      hi: 'एक पॉलिसी वर्ष में बीमा कंपनी जितना अधिकतम देगी वह रकम।',
      mr: 'एका पॉलिसी वर्षात विमा कंपनी जास्तीत जास्त जितकी रक्कम देईल ती.',
    },
  },
  {
    id: 'premium',
    match: ['premium'],
    term: { en: 'Premium', hi: 'प्रीमियम', mr: 'प्रीमियम' },
    meaning: {
      en: 'The amount you pay to keep the policy active.',
      hi: 'पॉलिसी चालू रखने के लिए आप जो रकम भरते हैं।',
      mr: 'पॉलिसी सुरू ठेवण्यासाठी तुम्ही भरत असलेली रक्कम.',
    },
  },
  {
    id: 'cashless',
    match: ['cashless'],
    term: { en: 'Cashless', hi: 'कैशलेस', mr: 'कॅशलेस' },
    meaning: {
      en: 'The insurer pays the hospital directly, so you do not pay upfront (except your own share).',
      hi: 'बीमा कंपनी सीधे अस्पताल को भुगतान करती है, इसलिए आपको पहले पैसे नहीं देने पड़ते (अपने हिस्से को छोड़कर)।',
      mr: 'विमा कंपनी थेट रुग्णालयाला पैसे देते, त्यामुळे तुम्हाला आधी पैसे भरावे लागत नाहीत (तुमचा वाटा वगळता).',
    },
  },
  {
    id: 'reimbursement',
    match: ['reimbursement'],
    term: { en: 'Reimbursement', hi: 'रीइम्बर्समेंट', mr: 'रीइम्बर्समेंट' },
    meaning: {
      en: 'You pay the hospital first, then send bills to the insurer to get your money back.',
      hi: 'आप पहले अस्पताल को भुगतान करते हैं, फिर बिल भेजकर बीमा कंपनी से पैसे वापस पाते हैं।',
      mr: 'तुम्ही आधी रुग्णालयाला पैसे भरता, मग बिले पाठवून विमा कंपनीकडून परत मिळवता.',
    },
  },
  {
    id: 'tpa',
    match: ['TPA', 'third party administrator'],
    term: { en: 'TPA', hi: 'टीपीए', mr: 'टीपीए' },
    meaning: {
      en: 'Third Party Administrator: a company that handles claims on behalf of the insurer.',
      hi: 'थर्ड पार्टी एडमिनिस्ट्रेटर: बीमा कंपनी की ओर से क्लेम संभालने वाली कंपनी।',
      mr: 'थर्ड पार्टी अ‍ॅडमिनिस्ट्रेटर: विमा कंपनीच्या वतीने क्लेम हाताळणारी कंपनी.',
    },
  },
  {
    id: 'ped',
    match: ['pre-existing diseases', 'pre-existing disease', 'pre-existing', 'preexisting'],
    term: { en: 'Pre-existing disease', hi: 'पहले से मौजूद बीमारी', mr: 'आधीपासून असलेला आजार' },
    meaning: {
      en: 'An illness you already had before buying the policy. It is usually covered only after a waiting period.',
      hi: 'पॉलिसी लेने से पहले से मौजूद बीमारी। आमतौर पर यह प्रतीक्षा अवधि के बाद ही कवर होती है।',
      mr: 'पॉलिसी घेण्यापूर्वीपासून असलेला आजार. तो सहसा प्रतीक्षा कालावधीनंतरच कव्हर होतो.',
    },
  },
  {
    id: 'exclusion',
    match: ['exclusions', 'exclusion'],
    term: { en: 'Exclusion', hi: 'अपवर्जन', mr: 'वगळलेले' },
    meaning: {
      en: 'Something the policy will not pay for.',
      hi: 'ऐसी चीज़ जिसका खर्च पॉलिसी नहीं देगी।',
      mr: 'ज्याचा खर्च पॉलिसी देणार नाही अशी गोष्ट.',
    },
  },
  {
    id: 'prehosp',
    match: ['pre-hospitalisation', 'pre-hospitalization'],
    term: { en: 'Pre-hospitalisation', hi: 'भर्ती से पहले का खर्च', mr: 'दाखल होण्यापूर्वीचा खर्च' },
    meaning: {
      en: 'Tests and doctor costs in the days just before you are admitted, which some policies repay.',
      hi: 'भर्ती होने से ठीक पहले के दिनों के टेस्ट और डॉक्टर का खर्च, जिसे कुछ पॉलिसियाँ चुकाती हैं।',
      mr: 'दाखल होण्यापूर्वीच्या दिवसांतील चाचण्या व डॉक्टरांचा खर्च, जो काही पॉलिसी परत देतात.',
    },
  },
  {
    id: 'posthosp',
    match: ['post-hospitalisation', 'post-hospitalization'],
    term: { en: 'Post-hospitalisation', hi: 'छुट्टी के बाद का खर्च', mr: 'डिस्चार्जनंतरचा खर्च' },
    meaning: {
      en: 'Medicines and follow-up costs in the days after you leave hospital, which some policies repay.',
      hi: 'अस्पताल से छुट्टी के बाद के दिनों की दवाओं और फॉलो-अप का खर्च, जिसे कुछ पॉलिसियाँ चुकाती हैं।',
      mr: 'रुग्णालयातून सुटी मिळाल्यानंतरच्या दिवसांतील औषधे व पाठपुराव्याचा खर्च, जो काही पॉलिसी परत देतात.',
    },
  },
  {
    id: 'daycare',
    match: ['day-care', 'day care', 'daycare'],
    term: { en: 'Day-care procedure', hi: 'डे-केयर प्रक्रिया', mr: 'डे-केअर प्रक्रिया' },
    meaning: {
      en: 'Treatment that needs less than 24 hours in hospital, such as cataract surgery.',
      hi: 'ऐसा इलाज जिसमें अस्पताल में 24 घंटे से कम लगते हैं, जैसे मोतियाबिंद ऑपरेशन।',
      mr: 'ज्या उपचारांसाठी रुग्णालयात 24 तासांपेक्षा कमी वेळ लागतो, उदा. मोतीबिंदू शस्त्रक्रिया.',
    },
  },
  {
    id: 'preauth',
    match: ['pre-authorisation', 'pre-authorization', 'preauthorisation'],
    term: { en: 'Pre-authorisation', hi: 'पूर्व-अनुमति', mr: 'पूर्व-मंजुरी' },
    meaning: {
      en: 'Approval you must get from the insurer before a planned cashless admission.',
      hi: 'योजनाबद्ध कैशलेस भर्ती से पहले बीमा कंपनी से लेनी वाली मंज़ूरी।',
      mr: 'नियोजित कॅशलेस दाखल होण्यापूर्वी विमा कंपनीकडून घ्यावी लागणारी मंजुरी.',
    },
  },
  {
    id: 'intimation',
    match: ['intimation'],
    term: { en: 'Intimation', hi: 'सूचना देना', mr: 'कळवणे' },
    meaning: {
      en: 'Telling the insurer about the hospital admission within the time the policy allows.',
      hi: 'पॉलिसी में दिए समय के भीतर अस्पताल में भर्ती की जानकारी बीमा कंपनी को देना।',
      mr: 'पॉलिसीत दिलेल्या वेळेत रुग्णालयात दाखल झाल्याची माहिती विमा कंपनीला देणे.',
    },
  },
];

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** One regex per language: English spellings + the term as written in that language. */
const cache = new Map<Lang, { re: RegExp; byText: Map<string, GlossaryEntry> }>();
function matcher(lang: Lang) {
  const hit = cache.get(lang);
  if (hit) return hit;
  const byText = new Map<string, GlossaryEntry>();
  for (const g of GLOSSARY) {
    for (const m of [...g.match, g.term[lang]]) byText.set(m.toLowerCase(), g);
  }
  const alts = Array.from(byText.keys())
    .sort((a, b) => b.length - a.length) // longest first: "pre-existing disease" before "pre-existing"
    .map(escape)
    .join('|');
  // Letter-aware boundaries so Devanagari terms match too (\b does not work for them).
  const re = new RegExp(`(^|[^\\p{L}\\p{M}\\p{N}])(${alts})(?=$|[^\\p{L}\\p{M}\\p{N}])`, 'giu');
  const built = { re, byText };
  cache.set(lang, built);
  return built;
}

export type Piece = string | { text: string; entry: GlossaryEntry };

/** Split text into plain strings and glossary hits. */
export function splitByGlossary(text: string, lang: Lang): Piece[] {
  const { re, byText } = matcher(lang);
  const out: Piece[] = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = (m.index ?? 0) + m[1].length;
    const entry = byText.get(m[2].toLowerCase());
    if (!entry) continue;
    if (start > last) out.push(text.slice(last, start));
    out.push({ text: m[2], entry });
    last = start + m[2].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
