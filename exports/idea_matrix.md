# Ideen × Wettbewerb — Matrix (Stand 23.09.2026)

Prinzip (Owner-Pivot): nichts von Null suchen. Bestehende Ideen/Builds als
Inspiration + Wettbewerbs-Check. Verdict pro Seed:
**MEIDEN** = Feld überfüllt · **NUR-US** = gelöst, aber nicht hier ·
**LÜCKE** = Spieler da, aber wedge erkennbar · Belege = live recherchiert.

| # | Pain-Seed (unsere Idee) | Wer baut das schon? | Preis-Level | Verdict | Unser möglicher Wedge |
|---|---|---|---|---|---|
| 1 | Inventar-Lücke kleine Hausverwalter (33-Wohnungen-Post) | RentBase, Lettly, Easy Properties (alle US); Property Inventory Tracker (UK); DACH: immocloud, casavi, objego, hausify — alles *Verwaltungs-Suiten* | $12–29/mo US; €5–10 DACH Suiten | **LÜCKE (DACH)** | US-Tools beweisen Zahlungsbereitschaft fürs Einfach-Modell; DACH-Suiten sind schwer & WEG-zentriert. Leichtes Geräte-/Einheit-Inventar + Übergabeprotokoll für Verwalter 10–100 WE existiert nicht als Eigenprodukt |
| 2 | POS zwingt Werbung/Support blockiert Kasse | Shift4/Toast/Clover-Klagen dokumentiert („cancellation extremely difficult"); Litterbox = XCancel für Consumer-Abo | POS $49–99/mo | **NUR-US (Teil)** | Kein „Exit-/Kündigungs-Assistent POS" als Produkt. Kleines Tool + Anwalts-Brief-Template (DAG/BGB §312k + Kündigungsanspruch 2022!) = Micro-SaaS oder Lead-Magnet |
| 3 | Vendor-Lock-in Kündigung (Uniform-Firma) | Litterbox (XCancel iOS/Mac, Indie), Truebill/RocketMoney (Consumer) | — | **LÜCKE (B2B)** | Consumer gelöst, **Kleinbetrieb-B2B ungelistet**: Verträge, Lieferanten, Dienstleister kündigen für 1–20-Mitarbeiter-Firmen. DACH-Rechtslage macht's wertvoller |
| 4 | IVR/Telefon kann keine Bestellungen (Restaurant) | Loman AI, Foodie Calls, Phone2 ($89 flat), Smith.ai; **DACH: handwerker-telefon-ki.de existiert**, ToolTime hat KI-Telefon schon in Handwerkersuite | $89–700/mo | **MEIDEN** | Frontal besetzt, auch DE. Nur noch Nische „Bestellung→POS-Sync DE-Gastronomie mit deutschen Sprachmenüs" — aber auch dort: Timeria etc. Inspiration ja, Übernehmen nein |
| 5 | Broker-Outreach = Spam, kein Vertrauen (Fracht) | Reesor/transportationrecovery (Inkasso, Contingency), FreightCaviar-artikel: TFX/Highway bauen Trust-Exchange; 123Loadboard etabliert | Inkasso %-Satz | **LÜCKE (DE/AT)** | US löst Betrug mit Debt-Collection + Loadboard-Gatekeeping. DE: „Seriositäts-Check Spedition" (MC-Register-Pendant = Gewa/OSS) als Gratis-Check mit Paid-API = klassisches Trojan-Horse-Modell |
| 6 | QB-Migration ohne Ziel-Auswahl | AccountingMD (Service), Crestwood „90-Day Migration" (Beratung) — **alle Services, kein Self-Serve-Produkt** | $2–10k Services | **LÜCKE** | „Migration-Readiness-Checker": welche Konten/Reports müssen mit, was geht verloren — als Self-Serve-Tool. DACH-Variantel: DATEV-Umzüge sind noch unübersichtlicher |
| 7 | PDF→Excel Angst (20 Seiten, Genauigkeit) | Lido 9.5/10, DocuClipper „99.9%", Basware, Envoice (€13/mo EU), Textract | $39/mo–enterprise | **MEIDEN** | Totales Overcrowding, Riesen-Investoren. Nur als Feature andernorts, nie als Produkt |
| 8 | Lead-Follow-up im Feld kaputt (sweatystartup 6×) | Salesforce Koa (Nvidia-Modell!), Pipedrive, Close, GoHighLevel (DACH: eversports-Nischen) | $29–150/user/mo | **MEIDEN (CRM) / LÜCKE (Micro)** | Voll-CRMs tot. Aber „Follow-up-Erinnerer nur für 1-Mann-Betriebe per WhatsApp/Signal DE" — GoHighLevel-Playbook existiert, deutsche handwerkliche Umsetzung dünn |
| 9 | Google-Phone-Spam auf GMB-Listings | Reviews.io, NiceJob, Podium (Reputation), kein Spam-Filter für GMB-Kontaktanfragen | $99–499/mo | **NUR-US-Teil** | Problem ist eher Plattform-Gap (Google), nicht Produkt-Markt. Low value |
| 10 | Digitales Menü „komplizierter als nötig" | Menulux/OrderYoo/Loman bauen das bereits, QR-Generator-Flut | $0–99/mo | **MEIDEN** | Commodity |
| 11 | Close-Rate erklärt nicht WARUM Rep gewinnt | Gong, Chorus/Zoom, Streller (DE!) | $$$ | **MEIDEN** | Enterprise-Sales-Intelligence, verrannt |
| 12 | Impersonation→Datenleck-Verdacht (Vertrieb) | Proofpoint, Mimecast + alle Email-Security-Anbieter | enterprise | **MEIDEN** | Security-Ozean |

## Fazit-Ranking (nach Geh-Reife, nicht nach Pain)

1. **#1 Inventar DACH-Kleinverwalter** — zahlende US-Vorbilder (RentBase/Lettly),
   DACH nur Suiten, unser Pain-Beleg ist selbst ein Verwalter mit 33 WE.
2. **#3 B2B-Kündigungs-Assistent (Lock-in)** — Consumer gelöst, B2B leer,
   DACH-Rechtslage = Bonus statt Hürde. #2 ist dieselbe Familie.
3. **#6 Migrations-Readiness-Checker** — Services beweisen Nachfrage,
   kein Produkt füllt die Mitte. DATEV-Winkel = DACH-Unfair Advantage.
4. #5 Trust-Check Spedition — gut aber Vertriebs-zentriert, schwerer Einstieg.

## Was der Radar ab jetzt täglich tut
scripts/opportunity_radar.py (Cron 08:30) matcht neue PH/HN-Launches gegen genau diese
12 Seeds — jeder neue Spieler in Seed 1 oder 3 = Warnung ODER
Beweis, dass der Markt zahlt.
