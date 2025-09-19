# app.py

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import io
import numpy as np
import traceback

# -------------------------
# Page configuration
# -------------------------
st.set_page_config(
    page_title="U.S. County Environmental Impact Viewer",
    page_icon="🗺️",
    layout="wide"
)

st.title("U.S. County Environmental Impact Viewer")
st.markdown("Visualize environmental impacts across all U.S. counties!")

# -------------------------
# Utility formatting funcs
# -------------------------
def format_to_3_sig_figs(value):
    """Format a number to 3 significant digits"""
    if value == 'N/A' or pd.isna(value):
        return 'N/A'
    try:
        value = float(value)
        if value == 0:
            return '0.00'
        import math
        if abs(value) >= 1:
            digits_before_decimal = int(math.floor(math.log10(abs(value)))) + 1
            decimal_places = max(0, 3 - digits_before_decimal)
        else:
            decimal_places = -int(math.floor(math.log10(abs(value)))) + 2
        return f"{value:.{decimal_places}f}"
    except (ValueError, TypeError, OverflowError):
        return 'N/A'

def format_carbon_footprint_scientific(value):
    if value == 'N/A' or pd.isna(value):
        return 'N/A'
    try:
        value = float(value)
        if value == 0:
            return '0.00e+00'
        return f"{value:.2e}"
    except (ValueError, TypeError, OverflowError):
        return 'N/A'

def format_water_footprint_scientific(value):
    if value == 'N/A' or pd.isna(value):
        return 'N/A'
    try:
        value = float(value)
        if value == 0:
            return '0.00e+00'
        return f"{value:.2e}"
    except (ValueError, TypeError, OverflowError):
        return 'N/A'

def format_water_scarcity_footprint_scientific(value):
    if value == 'N/A' or pd.isna(value):
        return 'N/A'
    try:
        value = float(value)
        if value == 0:
            return '0.00e+00'
        return f"{value:.2e}"
    except (ValueError, TypeError, OverflowError):
        return 'N/A'

# -------------------------
# Percentile category function
# -------------------------
def calculate_percentile_category(values):
    """Calculate percentile categories for color coding (green/yellow/red/gray)."""
    numeric_values = []
    for val in values:
        if val != 'N/A' and not pd.isna(val):
            try:
                numeric_values.append(float(val))
            except (ValueError, TypeError):
                continue
    if len(numeric_values) == 0:
        return ['gray'] * len(values)
    p33 = np.percentile(numeric_values, 33)
    p67 = np.percentile(numeric_values, 67)
    colors = []
    for val in values:
        if val == 'N/A' or pd.isna(val):
            colors.append('gray')
        else:
            try:
                num_val = float(val)
                if num_val <= p33:
                    colors.append('green')
                elif num_val <= p67:
                    colors.append('yellow')
                else:
                    colors.append('red')
            except (ValueError, TypeError):
                colors.append('gray')
    return colors

# -------------------------
# Data loading functions
# -------------------------
@st.cache_data
def load_data():
    """Load and process county data from kjhealy/fips-codes (robust to encoding)."""
    try:
        counties_url = "https://raw.githubusercontent.com/kjhealy/fips-codes/master/county_fips_master.csv"
        response = requests.get(counties_url)
        response.raise_for_status()

        encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
        for encoding in encodings_to_try:
            try:
                content = response.content.decode(encoding)
                counties = pd.read_csv(io.StringIO(content))
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("Could not decode the FIPS reference CSV with attempted encodings")

        # Ensure relevant columns exist and are clean
        if not {'state_name', 'county_name', 'fips'}.issubset(counties.columns):
            # attempt to rename typical columns if mismatch
            counties = counties.rename(columns={c: c.strip() for c in counties.columns})

        counties = counties.dropna(subset=['state_name', 'county_name', 'fips'])
        counties['fips'] = counties['fips'].astype(str).str.zfill(5)
        # If there is a state abbreviation column, keep it; otherwise create placeholder
        if 'state_abbr' not in counties.columns:
            counties['state_abbr'] = counties['state_name'].apply(lambda s: (s[:2].upper() if isinstance(s, str) else '??'))
        return counties
    except Exception as e:
        st.error(f"Error loading county data: {e}")
        return None

@st.cache_data
def load_emission_data():
    """Load emission factors from inputdata.xlsx (expected columns but robust)."""
    try:
        emission_df = pd.read_excel('inputdata.xlsx', header=None)
        # If the file has headers already, handle that by checking dtypes
        if emission_df.shape[1] < 5:
            raise ValueError("inputdata.xlsx must contain at least 5 columns (fips, EWIF, EF, ACF, SWI)")
        emission_df = emission_df.iloc[:, :5]  # take first 5 columns if more exist
        emission_df.columns = ['fips_raw', 'EWIF', 'EF', 'ACF', 'SWI']
        emission_df['fips'] = emission_df['fips_raw'].astype(str).str.zfill(5)
        emission_df = emission_df.dropna(subset=['fips_raw', 'EF'])
        return emission_df[['fips', 'EWIF', 'EF', 'ACF', 'SWI']]
    except FileNotFoundError:
        st.error("Error: 'inputdata.xlsx' not found in the working directory. Please add the file.")
        return None
    except Exception as e:
        st.error(f"Error loading emission data: {e}")
        return None

@st.cache_data
def load_geojson():
    """Load geographic boundary data for counties (Plotly geojson)."""
    try:
        url = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Error loading map data: {e}")
        return None

# -------------------------
# Converters
# -------------------------
def convert_to_kwh_per_year(power_value, units):
    if units == "kWh/yr":
        return power_value
    elif units == "kWh/mo":
        return power_value * 12
    elif units == "kW":
        return power_value * 8760
    elif units == "MW":
        return power_value * 1000 * 8760
    else:
        return 0

def convert_to_liters_per_year(water_value, units):
    if units == "L/yr":
        return water_value
    elif units == "L/mo":
        return water_value * 12
    elif units == "L/s":
        return water_value * 31557600
    elif units == "gpm":
        return water_value * 525600 * 3.78541
    elif units == "gal/mo":
        return water_value * 12 * 3.78541
    else:
        return 0

# -------------------------
# Load datasets (with spinner)
# -------------------------
with st.spinner("Loading data..."):
    data = load_data()               # county ref (fips -> county_name, state_name)
    geojson = load_geojson()         # full US counties geojson
    emission_data = load_emission_data()  # your inputdata.xlsx

if data is None or geojson is None:
    st.error("Failed to load required data. Please refresh the page to try again.")
    st.stop()

if emission_data is None:
    st.warning("Emission data could not be loaded. The app will work without emission factors.")
    emission_data = pd.DataFrame(columns=['fips', 'EWIF', 'EF', 'ACF', 'SWI'])

# -------------------------
# Layout & controls (left column)
# -------------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Environmental Impact Metric")
    impact_metric = st.selectbox(
        "Choose Environmental Impact:",
        ["Carbon Footprint", "Scope 1 & 2 Water Footprint", "Water Scarcity Footprint"],
        help="Select the environmental impact metric to visualize on the map"
    )

    st.markdown("---")
    st.subheader("On-Site Power Generation")
    power_col1, power_col2 = st.columns([2, 1])
    with power_col1:
        onsite_power = st.number_input(
            "On-Site Power:",
            min_value=0.0,
            value=0.0,
            step=1.0,
            format="%.2f",
            help="Enter the amount of on-site power generation"
        )
    with power_col2:
        power_units = st.selectbox(
            "Units:",
            ["kWh/yr", "kWh/mo", "kW", "MW"],
            help="Select the units for on-site power"
        )
    if onsite_power > 0:
        st.info(f"**On-Site Power:** {onsite_power:,.2f} {power_units}")

    st.markdown("---")
    st.subheader("On-Site Water Consumption")
    water_col1, water_col2 = st.columns([2, 1])
    with water_col1:
        onsite_water = st.number_input(
            "On-Site Water:",
            min_value=0.0,
            value=0.0,
            step=1.0,
            format="%.2f",
            help="Enter the amount of on-site water consumption"
        )
    with water_col2:
        water_units = st.selectbox(
            "Units:",
            ["L/yr", "L/mo", "L/s", "gpm", "gal/mo"],
            help="Select the units for on-site water consumption"
        )
    if onsite_water > 0:
        st.info(f"**On-Site Water:** {onsite_water:,.2f} {water_units}")

    onsite_power_kwh_per_year = convert_to_kwh_per_year(onsite_power, power_units)
    onsite_water_l_per_year = convert_to_liters_per_year(onsite_water, water_units)

    if onsite_power > 0:
        st.write(f"**Converted Power:** {onsite_power_kwh_per_year:,.0f} kWh/year")
    if onsite_water > 0:
        st.write(f"**Converted Water:** {onsite_water_l_per_year:,.0f} L/year")

    # --- STATE FILTER ---
    st.markdown("---")
    st.subheader("State")
    if data is not None:
        state_options = ["All States"] + sorted(data["state_name"].dropna().unique().tolist())
    else:
        state_options = ["All States"]
    selected_state = st.selectbox(
        "Filter by State:",
        state_options,
        help="Select a state to view only its counties, or choose 'All States' to view all counties"
    )

# -------------------------
# Map and plotting (right column)
# -------------------------
with col2:
    st.subheader("County Map")
    st.markdown("""
    **Color Legend:**
    - 🟢 **Green**: Below 33rd percentile (lowest impact)
    - 🟡 **Yellow**: 33rd-67th percentile (medium impact)  
    - 🔴 **Red**: Above 67th percentile (highest impact)
    - ⚫ **Gray**: No data available
    """)

    try:
        # Build a dataframe of counties from the GEOJSON (IDs align with geojson features)
        all_fips = [str(feat.get('id')) for feat in geojson.get('features', [])]
        plot_df = pd.DataFrame({'fips': all_fips})

        # Merge with county reference and emission inputs (do not mutate global 'data')
        plot_df = plot_df.merge(
            data[['fips', 'county_name', 'state_name', 'state_abbr']],
            on='fips', how='left'
        ).merge(
            emission_data[['fips', 'EF', 'EWIF', 'ACF', 'SWI']],
            on='fips', how='left'
        )

        # Fill missing values
        plot_df['county_name'] = plot_df['county_name'].fillna('Unknown County')
        plot_df['state_name'] = plot_df['state_name'].fillna('Unknown State')
        plot_df['state_abbr'] = plot_df['state_abbr'].fillna('??')
        plot_df['EF'] = plot_df['EF'].fillna('N/A')
        plot_df['EWIF'] = plot_df['EWIF'].fillna('N/A')
        plot_df['ACF'] = plot_df['ACF'].fillna('N/A')
        plot_df['SWI'] = plot_df['SWI'].fillna('N/A')

        # Apply state filter to plot_df (local only)
        if selected_state != "All States":
            plot_df = plot_df[plot_df['state_name'] == selected_state]

        # Build set of FIPS we'll show (to filter geojson)
        fips_to_plot = set(plot_df['fips'].dropna().astype(str).tolist())

        # Build filtered geojson with only the features matching fips_to_plot
        if selected_state != "All States" and len(fips_to_plot) > 0:
            filtered_features = [feat for feat in geojson.get('features', []) if str(feat.get('id')) in fips_to_plot]
            if len(filtered_features) == 0:
                # fallback - nothing matched; keep full geojson but inform user
                st.warning(f"No counties found for state '{selected_state}' in the loaded datasets. Showing full US map.")
                filtered_geojson = geojson
            else:
                filtered_geojson = {"type": "FeatureCollection", "features": filtered_features}
        else:
            filtered_geojson = geojson

        # ---------- Calculations ----------
        # Carbon footprint (kgCO2e/year)
        def calculate_carbon_footprint(ef_value, power_kwh_year):
            if ef_value == 'N/A' or pd.isna(ef_value) or power_kwh_year == 0:
                return 'N/A'
            try:
                return float(ef_value) * power_kwh_year
            except (ValueError, TypeError):
                return 'N/A'

        # Water footprint: Wsite + EWIF*Psite
        def calculate_water_footprint(ewif_value, power_kwh_year, water_l_year):
            if ewif_value == 'N/A' or pd.isna(ewif_value):
                return water_l_year if water_l_year > 0 else 'N/A'
            try:
                ewif_contribution = float(ewif_value) * power_kwh_year
                total_wf = water_l_year + ewif_contribution
                return total_wf
            except (ValueError, TypeError):
                return water_l_year if water_l_year > 0 else 'N/A'

        # Water scarcity footprint: ACF*Wsite + SWI*Psite
        def calculate_water_scarcity_footprint(acf_value, swi_value, power_kwh_year, water_l_year):
            acf_contribution = 0
            swi_contribution = 0
            if acf_value != 'N/A' and not pd.isna(acf_value):
                try:
                    acf_contribution = float(acf_value) * water_l_year
                except (ValueError, TypeError):
                    acf_contribution = 0
            if swi_value != 'N/A' and not pd.isna(swi_value):
                try:
                    swi_contribution = float(swi_value) * power_kwh_year
                except (ValueError, TypeError):
                    swi_contribution = 0
            total_wsf = acf_contribution + swi_contribution
            if total_wsf == 0 and water_l_year == 0 and power_kwh_year == 0:
                return 'N/A'
            return total_wsf

        # Add columns (use the converted onsite kWh/year and L/year)
        plot_df['carbon_footprint'] = plot_df['EF'].apply(lambda ef: calculate_carbon_footprint(ef, onsite_power_kwh_per_year))
        plot_df['water_footprint'] = plot_df['EWIF'].apply(lambda ewif: calculate_water_footprint(ewif, onsite_power_kwh_per_year, onsite_water_l_per_year))
        plot_df['water_scarcity_footprint'] = plot_df.apply(lambda row: calculate_water_scarcity_footprint(row['ACF'], row['SWI'], onsite_power_kwh_per_year, onsite_water_l_per_year), axis=1)

        # Format tooltip columns
        plot_df['EF_formatted'] = plot_df['EF'].apply(format_to_3_sig_figs)
        plot_df['carbon_footprint_formatted'] = plot_df['carbon_footprint'].apply(format_carbon_footprint_scientific)
        plot_df['water_footprint_formatted'] = plot_df['water_footprint'].apply(format_water_footprint_scientific)
        plot_df['water_scarcity_footprint_formatted'] = plot_df['water_scarcity_footprint'].apply(format_water_scarcity_footprint_scientific)

        # Choose metric & unit
        if impact_metric == "Carbon Footprint":
            metric_column = 'carbon_footprint'
            metric_formatted_column = 'carbon_footprint_formatted'
            metric_unit = 'kgCO2e/year'
        elif impact_metric == "Scope 1 & 2 Water Footprint":
            metric_column = 'water_footprint'
            metric_formatted_column = 'water_footprint_formatted'
            metric_unit = 'L/year'
        else:
            metric_column = 'water_scarcity_footprint'
            metric_formatted_column = 'water_scarcity_footprint_formatted'
            metric_unit = 'L/year'

        # Color categories & numeric map
        plot_df['color_category'] = calculate_percentile_category(plot_df[metric_column])
        color_map = {'green': 0, 'yellow': 1, 'red': 2, 'gray': 3}
        plot_df['color_numeric'] = plot_df['color_category'].map(color_map)

        # Debug info (optional but useful)
        st.write(f"Selected metric: {impact_metric}")
        st.write(f"Counties plotted: {len(plot_df)}  |  GeoJSON features included: {len(filtered_geojson.get('features', []))}")

        # ---------- Plot using filtered_geojson ----------
        fig = px.choropleth(
            plot_df,
            geojson=filtered_geojson,
            locations='fips',
            color='color_numeric',
            color_continuous_scale=[
                [0, 'green'],
                [0.33, 'yellow'],
                [0.67, 'red'],
                [1, 'gray']
            ],
            range_color=(0, 3),
            scope="usa",
            title=f"{impact_metric} by County" + (f" — {selected_state}" if selected_state != "All States" else ""),
            hover_name='county_name',
            hover_data={
                'state_name': ':',
                'state_abbr': ':',
                'fips': ':',
                'color_numeric': False
            },
            custom_data=['county_name', 'state_name', 'state_abbr', 'fips',
                         'EF_formatted', 'carbon_footprint_formatted', 'water_footprint_formatted',
                         'water_scarcity_footprint_formatted', 'color_category']
        )

        # Zoom logic: zoom to selection only when a single state is chosen
        if selected_state == "All States":
            fig.update_geos(scope="usa", visible=False)
        else:
            fig.update_geos(fitbounds="locations", visible=False)

        # Styling
        fig.update_traces(marker_line_color='white', marker_line_width=0.5, showscale=False)
        fig.update_geos(projection_type="albers usa", showlakes=True, lakecolor="lightblue", bgcolor="white")
        fig.update_layout(margin={"r":0,"t":40,"l":0,"b":0}, coloraxis_showscale=False, height=600)

        # Hover template
        fig.update_traces(
            hovertemplate="<b>%{customdata[0]}</b><br>"
                          "State: %{customdata[1]} (%{customdata[2]})<br>"
                          "FIPS: %{customdata[3]}<br>"
                          "Carbon Emission Factor: %{customdata[4]}<br>"
                          "Carbon Footprint: %{customdata[5]} kgCO2e/year<br>"
                          "Water Footprint: %{customdata[6]} L/year<br>"
                          "Water Scarcity Footprint: %{customdata[7]} L/year<br>"
                          "Impact Category: %{customdata[8]}<br>"
                          "<extra></extra>"
        )

        st.plotly_chart(fig, use_container_width=True)

        # ---------- Stats ----------
        valid_values = []
        for val in plot_df[metric_column]:
            if val != 'N/A' and not pd.isna(val):
                try:
                    valid_values.append(float(val))
                except (ValueError, TypeError):
                    continue
        if len(valid_values) > 0:
            p33 = np.percentile(valid_values, 33)
            p67 = np.percentile(valid_values, 67)
            st.markdown(f"""
            **{impact_metric} Statistics:**
            - **33rd Percentile:** {p33:.2e} {metric_unit}
            - **67th Percentile:** {p67:.2e} {metric_unit}
            - **Counties with data:** {len(valid_values)} out of {len(plot_df)}
            """)
        else:
            st.warning(f"No valid data available for {impact_metric}")

    except Exception as e:
        st.error(f"Error creating map: {e}")
        st.error(traceback.format_exc())

# Footer
st.markdown("---")
st.markdown("""
**Data Sources:**
- County FIPS codes from Kieran Healy's FIPS codes repository (kjhealy/fips-codes)
- Geographic boundaries from Plotly GeoJSON data

**How to use:** 
1. Select an environmental impact metric to visualize
2. Enter on-site power and water consumption values to see calculated impacts across counties (and optionally filter by state)
3. The map will color-code counties based on percentiles of the selected environmental impact
""")
