import streamlit as st
import cloudscraper
from bs4 import BeautifulSoup
import pandas as pd
import pulp
import time
import re
import random
import altair as alt
import os
import unicodedata

# --- CONFIGURATIE ---
st.set_page_config(page_title="Wielermanager 2026 Pro", layout="wide")

# Bestandsnaam van jouw gescrapte prijzen
PRICE_FILE = "sporza_alle_renners.csv"

# Scraper instellen
scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# --- DATABASES ---
CLASSICS_INFO = {
    "Omloop Nieuwsblad": "Kasseien", 
    "Kuurne - Brussel - Kuurne": "Sprint",
    "Strade Bianche": "Gravel", 
    "Milano-Sanremo": "Sprint",
    "Danilith Nokere Koerse": "Sprint", 
    "Bredene Koksijde Classic": "Sprint",
    "Ronde Van Brugge": "Sprint", 
    "E3 Saxo Classic": "Kasseien",
    "In Flanders Fields - From Middelkerke to Wevelgem": "Sprint", # Gent-Wevelgem
    "Dwars door Vlaanderen": "Kasseien",
    "Ronde van Vlaanderen": "Kasseien", 
    "Scheldeprijs": "Sprint",
    "Brabantse Pijl": "Heuvels", 
    "Amstel Gold Race": "Heuvels",
    "La Flèche Wallonne": "Heuvels", 
    "Liège-Bastogne-Liège": "Heuvels",
    "Paris-Roubaix": "Kasseien"
}
CLASSICS_NAMES = list(CLASSICS_INFO.keys())

# --- FUNCTIES VOOR PRIJS-MATCHING ---

def normalize_name(name):
    """Verwijdert accenten en witruimte voor betere matching (bijv. Pogačar -> pogacar)"""
    if not isinstance(name, str):
        return ""
    nfkd_form = unicodedata.normalize('NFKD', name)
    name_clean = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return name_clean.strip().lower()

def load_official_prices():
    """Laadt prijzen in en normaliseert namen voor de dictionary sleutels."""
    if not os.path.exists(PRICE_FILE):
        return {}
    try:
        # utf-8-sig vangt eventuele Byte Order Marks in CSV op
        price_df = pd.read_csv(PRICE_FILE, encoding='utf-8-sig')
        price_dict = {}
        for _, row in price_df.iterrows():
            try:
                # Prijs opschonen
                raw_p = str(row['Prijs'])
                clean_price = raw_p.replace('€', '').replace('M', '').replace(',', '.').strip()
                price_float = float(clean_price)
                
                # Naam als genormaliseerde sleutel
                name_key = normalize_name(str(row['Naam']))
                price_dict[name_key] = price_float
            except:
                continue
        return price_dict
    except Exception as e:
        st.error(f"Fout bij lezen prijsbestand: {e}")
        return {}

# Initialiseer de prijzen
OFFICIAL_PRICES = load_official_prices()

def get_rider_stats(rider_url, rider_name_pcs):
    try:
        # --- PRIJS OPZOEKEN (FIXED) ---
        search_name = normalize_name(rider_name_pcs)
        price = OFFICIAL_PRICES.get(search_name, 0.0) 

        # Fuzzy fallback: als de naam van PCS onderdelen bevat die in onze lijst staan
        if price == 0.0:
            parts = search_name.split()
            if len(parts) >= 2:
                # Zoek of voornaam EN achternaam ergens in een CSV-naam voorkomen
                for key, val in OFFICIAL_PRICES.items():
                    if parts[0] in key and parts[-1] in key:
                        price = val
                        break
        
        if price == 0.0:
            price = 2.0 # Minimum prijs

        # --- SCRAPEN ---
        response = scraper.get(rider_url, headers=headers)
        if response.status_code != 200: return 0, 0, "", 25, 70, price
        soup = BeautifulSoup(response.text, "html.parser")
        txt = soup.get_text()
        
        age, weight = 25, 70 
        try:
            age_match = re.search(r'Age:.*?(\d{2})', txt)
            if age_match: age = int(age_match.group(1))
            w_match = re.search(r'Weight:.*?(\d{2,3})', txt)
            if w_match: weight = int(w_match.group(1))
        except: pass

        race_names = []
        program_header = soup.find("h4", string=re.compile("Program|Upcoming"))
        if program_header:
            program_ul = program_header.find_next("ul")
            if program_ul:
                for a in program_ul.find_all("a"):
                    if "more" not in a.text.lower() and a.text.strip():
                        race_names.append(a.text.strip())
        
        if not race_names:
            program_div = soup.select_one("div.rdr-season-stats")
            if program_div:
                for a in program_div.find_all('a'):
                    race_names.append(a.text.strip())

        classic_count = 0
        races_found = []
        for name in race_names:
            for c_name in CLASSICS_NAMES:
                if c_name in name and c_name not in races_found:
                    classic_count += 1
                    races_found.append(c_name)
                    break 
        
        found_points = []
        history_table = soup.select("table.basic tbody tr")
        for row in history_table:
            row_txt = row.get_text()
            if any(y in row_txt[:15] for y in ["2026", "2025", "2024"]): 
                title_div = row.select_one("div.title") or row.find_all("td")[-1]
                if title_div:
                    raw = re.sub(r'\D', '', title_div.get_text())
                    if raw.isdigit(): found_points.append(int(raw))

        season_sum = soup.select_one("div.rdrSeasonSum")
        if season_sum:
            sum_text = season_sum.get_text()
            uci_match = re.search(r'UCI points:\s*(\d+)', sum_text)
            if uci_match: found_points.append(int(uci_match.group(1)))
            pcs_match = re.search(r'PCS points:\s*(\d+)', sum_text)
            if pcs_match: found_points.append(int(pcs_match.group(1)))

        points = max(found_points) if found_points else 0
        return classic_count, points, ", ".join(races_found), age, weight, price
    except: return 0, 0, "", 25, 70, 2.0

@st.cache_data(ttl=3600)
def scrape_team_data(team_urls):
    all_riders = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    seen_urls = set()
    total = len(team_urls)

    for i, team_url in enumerate(team_urls):
        team_name = team_url.split("/")[-1].replace("-", " ").title()
        status_text.text(f"Scrapen ({i+1}/{total}): {team_name}...")
        try:
            time.sleep(random.uniform(0.4, 0.8))
            response = scraper.get(team_url, headers=headers)
            if response.status_code != 200:
                st.error(f"PCS blokkeert toegang: Status {response.status_code}")
        except Exception as e:
            st.error(f"Er ging iets mis: {e}")
        #     response = scraper.get(team_url, headers=headers)
        #     if response.status_code == 200:
        #         soup = BeautifulSoup(response.text, "html.parser")
        #         rider_items = soup.select('div.page-content > ul.list li a') or soup.select('ul.list a')

        #         for a in rider_items:
        #             href = a.get('href', '')
        #             if "rider/" in href and "statistics" not in href:
        #                 full_url = href if href.startswith("http") else f"https://www.procyclingstats.com/{href.lstrip('/')}"
        #                 if full_url not in seen_urls:
        #                     seen_urls.add(full_url)
        #                     name_from_list = a.text.strip()
                            
        #                     races, points, race_list, age, weight, price = get_rider_stats(full_url, name_from_list)
                            
        #                     exp_score = (points * 0.2) + (races * 60)
        #                     if age < 25: exp_score *= 1.1

        #                     all_riders.append({
        #                         "Naam": name_from_list, "Team": team_name, "Leeftijd": age,
        #                         "Gewicht": weight, "Prijs": price, "Races": races,
        #                         "Punten": points, "Verwachte_Score": exp_score,
        #                         "Programma": race_list
        #                     })
        # except: pass
        # progress_bar.progress((i + 1) / total)
        
    status_text.text("Klaar!")
    df = pd.DataFrame(all_riders)
    if not df.empty:
        df = df.drop_duplicates(subset=['Naam'], keep='first').sort_values(by="Punten", ascending=False)
    return df

def optimize_team(df, budget, min_riders, max_riders, min_per_race, min_per_sprint, max_starters_allowed):
    df_active = df[(df['Races'] > 0) | (df['Punten'] > 20)].reset_index(drop=True)
    if df_active.empty: return pd.DataFrame()

    races_list = CLASSICS_NAMES 
    race_value_per_rider = {}
    rider_races_map = {}

    for i, row in df_active.iterrows():
        n_races = row['Races']
        race_value_per_rider[i] = (row['Verwachte_Score'] / n_races) if n_races > 0 else 0
        rider_races_map[i] = [r for r in races_list if r in str(row['Programma'])]

    prob = pulp.LpProblem("Wielermanager", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("TeamSelection", df_active.index, cat='Binary')
    y = {}
    for i in df_active.index:
        for r in races_list:
            y[(i, r)] = pulp.LpVariable(f"Start_{i}_{r}", cat='Binary')

    total_points = []
    for i in df_active.index:
        for r in rider_races_map[i]:
            total_points.append(y[(i, r)] * race_value_per_rider[i])
    prob += pulp.lpSum(total_points)

    prob += pulp.lpSum([df_active['Prijs'][i] * x[i] for i in df_active.index]) <= budget
    prob += pulp.lpSum([x[i] for i in df_active.index]) <= max_riders
    prob += pulp.lpSum([x[i] for i in df_active.index]) >= min_riders

    for i in df_active.index:
        for r in races_list:
            prob += y[(i, r)] <= x[i]
            if r not in rider_races_map[i]: prob += y[(i, r)] == 0

    for r in races_list:
        prob += pulp.lpSum([y[(i, r)] for i in df_active.index]) <= max_starters_allowed
        race_type = CLASSICS_INFO.get(r, "Overig")
        target_min = min_per_sprint if race_type == "Sprint" else min_per_race
        prob += pulp.lpSum([y[(i, r)] for i in df_active.index]) >= target_min

    prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] == 'Optimal':
        selected_indices = [i for i in df_active.index if x[i].value() == 1]
        result_df = df_active.iloc[selected_indices].copy()
        result_df['Geplande_Starts'] = [sum([y[(i, r)].value() for r in rider_races_map[i]]) for i in selected_indices]
        return result_df
    return pd.DataFrame()

# --- STREAMLIT UI ---

st.title("🚴 Wielermanager 2026 Pro")

if not OFFICIAL_PRICES:
    st.warning(f"⚠️ Let op: '{PRICE_FILE}' niet gevonden.")
else:
    st.success(f"✅ {len(OFFICIAL_PRICES)} officiële prijzen ingeladen.")

if "mijn_selectie" not in st.session_state:
    st.session_state["mijn_selectie"] = []

st.sidebar.header("⚙️ Team Instellingen")
budget = st.sidebar.number_input("Budget (M)", value=120.0, step=0.5)
min_r = st.sidebar.number_input("Min. Renners", value=20)
max_r = st.sidebar.number_input("Max. Renners", value=20)

st.sidebar.markdown("---")
st.sidebar.header("⚖️ Balans & Dekking")
min_dekking = st.sidebar.slider("Minimaal aantal per koers", 1, 10, 3)
min_sprint = st.sidebar.slider("Minimaal aantal bij SPRINTS", 1, 8, 5)
max_allowed = st.sidebar.slider("Max renners tellen per koers", 12, 20, 15)

default_teams = [
    "https://www.procyclingstats.com/team/alpecin-premier-tech-2026",
    "https://www.procyclingstats.com/team/bahrain-victorious-2026",
    "https://www.procyclingstats.com/team/decathlon-cma-cgm-team-2026",
    "https://www.procyclingstats.com/team/ef-education-easypost-2026",
    "https://www.procyclingstats.com/team/groupama-fdj-united-2026",
    "https://www.procyclingstats.com/team/ineos-grenadiers-2026",
    "https://www.procyclingstats.com/team/lidl-trek-2026",
    "https://www.procyclingstats.com/team/lotto-intermarche-2026",
    "https://www.procyclingstats.com/team/movistar-team-2026",
    "https://www.procyclingstats.com/team/nsn-cycling-team-2026",
    "https://www.procyclingstats.com/team/red-bull-bora-hansgrohe-2026",
    "https://www.procyclingstats.com/team/soudal-quick-step-2026",
    "https://www.procyclingstats.com/team/team-jayco-alula-2026",
    "https://www.procyclingstats.com/team/team-picnic-postnl-2026",
    "https://www.procyclingstats.com/team/team-visma-lease-a-bike-2026",
    "https://www.procyclingstats.com/team/uae-team-emirates-xrg-2026",
    "https://www.procyclingstats.com/team/uno-x-mobility-2026",
    "https://www.procyclingstats.com/team/xds-astana-team-2026",
    "https://www.procyclingstats.com/team/unibet-rose-rockets-2026",
    "https://www.procyclingstats.com/team/tudor-pro-cycling-team-2026",
    "https://www.procyclingstats.com/team/totalenergies-2026",
    "https://www.procyclingstats.com/team/team-polti-visitmalta-2026",
    "https://www.procyclingstats.com/team/team-novo-nordisk-2026",
    "https://www.procyclingstats.com/team/team-flanders-baloise-2026",
    "https://www.procyclingstats.com/team/solution-tech-nippo-rali-2026",
    "https://www.procyclingstats.com/team/pinarello-q365-pro-cycling-team-2026",
    "https://www.procyclingstats.com/team/modern-adventure-pro-cycling-2026",
    "https://www.procyclingstats.com/team/mbh-bank-csb-telecom-fort-2026",
    "https://www.procyclingstats.com/team/euskaltel-euskadi-2026",
    "https://www.procyclingstats.com/team/equipo-kern-pharma-2026",
    "https://www.procyclingstats.com/team/cofidis-2026",
    "https://www.procyclingstats.com/team/caja-rural-seguros-rga-2026",
    "https://www.procyclingstats.com/team/burgos-burpellet-bh-2026",
    "https://www.procyclingstats.com/team/bardiani-csf-7-saber-2026"
]

if 'scraped_data' not in st.session_state:
    st.session_state['scraped_data'] = pd.DataFrame()

if st.button("🚀 Start Analyse"):
    scrape_team_data.clear()
    with st.spinner('Teams aan het laden en prijzen koppelen...'):
        df = scrape_team_data(default_teams)
        st.session_state['scraped_data'] = df

if not st.session_state['scraped_data'].empty:
    df = st.session_state['scraped_data']
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🏆 Optimaal Team", "✍️ Stel je Team Samen", "🦄 Dark Horses", 
        "🔮 Koers Voorspeller", "📊 Data Check", "🔎 Zoek Renner"
    ])
    
    with tab1:
        st.subheader("Het Optimale Team")
        best = optimize_team(df, budget, min_r, max_r, min_dekking, min_sprint, max_allowed)
        if not best.empty:
            c1, c2, c3 = st.columns(3)
            c1.metric("Renners", len(best))
            c2.metric("Totaal Prijs", f"€ {best['Prijs'].sum():.1f}M")
            c3.metric("Verwachte Score", int(best['Verwachte_Score'].sum()))
            st.dataframe(best[['Naam', 'Team', 'Prijs', 'Races', 'Geplande_Starts', 'Programma']].style.format({"Prijs": "€ {:.1f}M"}))
            
            # Grafiek
            race_counts = {race: 0 for race in CLASSICS_NAMES}
            for _, row in best.iterrows():
                for race in CLASSICS_NAMES:
                    if race in str(row['Programma']): race_counts[race] += 1
            chart_data = pd.DataFrame([{"Koers": r, "Aantal": c} for r, c in race_counts.items()])
            st.altair_chart(alt.Chart(chart_data).mark_bar().encode(x=alt.X('Koers', sort=CLASSICS_NAMES), y='Aantal'), use_container_width=True)

    with tab2:
        all_names = sorted(df['Naam'].unique())
        selected = st.multiselect("Kies je team:", all_names, key="mijn_selectie")
        if selected:
            my_team = df[df['Naam'].isin(selected)]
            st.metric("Budget over", f"€ {budget - my_team['Prijs'].sum():.1f}M")
            st.dataframe(my_team[['Naam', 'Team', 'Prijs', 'Programma']])

    with tab3:
        st.subheader("🕵️ Dark Horses (<= 4.5M)")
        dh = df[df['Prijs'] <= 4.5].sort_values(by='Verwachte_Score', ascending=False)
        st.dataframe(dh[['Naam', 'Team', 'Prijs', 'Races', 'Punten']].head(30))

    with tab4:
        st.subheader("🔮 Koers Voorspeller")
        race = st.selectbox("Kies Koers:", CLASSICS_NAMES)
        starters = df[df['Programma'].str.contains(race, na=False)].copy()
        if not starters.empty:
            starters['Kans'] = starters['Punten']
            rt = CLASSICS_INFO[race]
            for i, r in starters.iterrows():
                w, s = r['Gewicht'], r['Kans']
                if rt == "Sprint": s *= 1.2 if w > 72 else 1.0
                elif rt == "Kasseien": s *= 1.2 if 72 < w < 82 else 1.0
                elif rt == "Heuvels": s *= 1.2 if w < 66 else 1.0
                starters.at[i, 'Kans'] = s
            st.dataframe(starters.sort_values(by='Kans', ascending=False)[['Naam', 'Prijs']].head(10))

    with tab5:
        st.dataframe(df)

    with tab6:
        q = st.text_input("Zoek renner:")
        if q:
            st.dataframe(df[df['Naam'].str.contains(q, case=False)])
