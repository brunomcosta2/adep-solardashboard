from flask import Flask, render_template, jsonify, send_from_directory
import time
from datetime import datetime
from fusion_solar_py.client import FusionSolarClient
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

#Configuration
accounts = [
    ("DomusSocial", "UpacsDM@2023FNT", "uni004eu5"),  # Porto Solar
    ("AEdP_EDS", "AEdP@2024", "uni003eu5"),  # Parque da Trindade
    ("UPAC_AMIAL", "amial2023", "uni003eu5"),  # Agra do Amial
    ("Adeporto", "Tribunal-2030", "uni001eu5"),  # Tribunal
    ("mapadeporto", "info-2030", "uni005eu5"), # MAP funcional
]

def custom_get_station_list(self) -> list:
    r = self._session.post(
        url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
        json={
            "curPage": 1,
            "pageSize": 50,  # increased limit
            "gridConnectedTime": "",
            "queryTime": self._get_day_start_sec(),
            "timeZone": 2,
            "sortId": "createTime",
            "sortDir": "DESC",
            "locale": "en_US"
        }
    )
    r.raise_for_status()
    obj_tree = r.json()
    if not obj_tree["success"]:
        raise Exception("Failed to retrieve station list")
    return obj_tree["data"]["list"]

# Monkey-patch the class
FusionSolarClient.get_station_list = custom_get_station_list

'''
accounts = [
    ("ID1", "PASS1", "uni004eu5"),  
    ("ID2", "PASS2", "uni003eu5"),  
    ("ID3", "PASS3", "uni003eu5"),  
    ("ID4", "PASS4", "uni001eu5"),  
    ("ID5", "PASS5", "uni005eu5"), 
]
'''

list_of_plants = [
    ("Escola Básica Fonte da Moura", "0"),
    ("Viveiros Municipais", "0"),
    ("Escola Básica Vilarinha", "0"),
    ("Polícia Municipal do Porto", "0"),
    ("Oficinas Domus", "0"),
    ("Regimento de Sapadores Bombeiros do Porto", "0"),
    ("Escola Básica Corujeira", "0"),
    ("Escola Básica Monte Aventino", "0"),
    ("Escola Básica Lomba", "0"),
    ("Escola Básica Paulo da Gama", "0"),
    ("Escola Básica Fontinha", "0"),
    ("Escola Básica Fernão Magalhães", "0"),
    ("Escola Básica Covelo", "0"),
    ("Escola Básica Viso", "0"),
    ("Escola Básica São João da Foz", "0"),
    ("Escola Básica Campinas", "0"),
    ("Escola Básica Alegria", "0"),
    ("Escola Básica Pasteleira", "0"),
    ("Escola Básica Condominhas", "0"),
    ("Escola Básica Castelos", "0"),
    ("Escola Básica Constituição", "0"),
    ("Escola Básica Torrinha", "0"),
    ("Escola Básica Miosótis", "0"),
    ("Escola Básica Augusto Lessa", "0"),
    ("Escola Básica Bom Pastor", "0"),
    ("Escola Básica Costa Cabral", "1"),
    ("Escola Básica Bom Sucesso", "0"),
    ("Escola Básica São Tomé", "0"),
    ("Escola Básica do Falcão", "0"),    
    ("TEATRO RIVOLI", "0"),
    ("Escola Básica das Antas", "0"),
    ("ETAR DE SOBREIRAS", "0"),
    ("Parque da Trindade", "0"),
    ("Bloco F - N67", "0"),
    ("Bloco E - N15", "0"),
    ("Bloco G - N83", "0"),
    ("Bloco F - N63", "0"),
    ("Bloco E - N29", "0"),
    ("Bloco D - N34", "0"),
    ("Bloco C - N62", "0"),
    ("Bloco C - N58", "0"),
    ("Bloco B - N72", "0"),
    ("Bloco B - N90", "0"),
    ("UPAC Pavilhão da Água e Energia &#x28;Edificio Administrativo&#x29;", "0"),
    ("UPAC Pavilhão da Água e Energia &#x28;Parque da Cidade&#x29;", "0"),
    ("Bloco H - N111", "0"),
    ("Bloco H-N115", "0"),
    ("Bloco A -N142", "0"),
    ("Bloco A -N138", "0"),
    ("Bloco A - N134", "0"),
    ("Escola EB1 Agra do Amial", "1"),
    ("TRP", "0"),
    ("TRP Museu", "1"),
    ("TRP Elevadores", "0"),
    ("MAP UPAC 2", "0"),
    ("MAP UPAC 1", "0"),    
]

@app.route("/")
def index():
    return render_template("index.html")  # This looks in the 'templates/' folder
    
class PowerStatus:
    """Class representing the basic power status"""

    def __init__(
        self,
        current_power_kw: float,
        energy_today_kwh: float = None,
        energy_kwh: float = None,
        **kwargs
    ):
        """Create a new PowerStatus object
        :param current_power_kw: The currently produced power in kW
        :type current_power_kw: float
        :param energy_today_kwh: The total power produced that day in kWh
        :type energy_today_kwh: float
        :param energy_kwh: The total power ever produced
        :type energy_kwh: float
        :param kwargs: Deprecated parameters
        """
        self.current_power_kw = current_power_kw
        self.energy_today_kwh = energy_today_kwh
        self.energy_kwh = energy_kwh

        if 'total_power_today_kwh' in kwargs.keys() and not energy_today_kwh:
            _LOGGER.warning(
                "The parameter 'total_power_today_kwh' is deprecated. Please use "
                "'energy_today_kwh' instead.", DeprecationWarning
            )
            self.energy_today_kwh = kwargs['total_power_today_kwh']

        if 'total_power_kwh' in kwargs.keys() and not energy_kwh:
            _LOGGER.warning(
                "The parameter 'total_power_kwh' is deprecated. Please use "
                "'energy_kwh' instead.", DeprecationWarning
            )
            self.energy_kwh = kwargs['total_power_kwh']

    @property
    def total_power_today_kwh(self):
        """The total power produced that day in kWh"""
        _LOGGER.warning(
            "The parameter 'total_power_today_kwh' is deprecated. Please use "
            "'energy_today_kwh' instead.")
        return self.energy_today_kwh

    @property
    def total_power_kwh(self):
        """The total power ever produced"""
        _LOGGER.warning(
            "The parameter 'total_power_kwh' is deprecated. Please use "
            "'energy_kwh' instead.")
        return self.energy_kwh

    def __repr__(self):
        return (f"PowerStatus(current_power_kw={self.current_power_kw}, "
                f"energy_today_kwh={self.energy_today_kwh}, "
                f"energy_kwh={self.energy_kwh})")

def get_current_plant_data(self, plant_id: str) -> dict:
        """Retrieve the current power status for a specific plant.
        :return: A dict object containing the whole data
        """

        url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/station-real-kpi"
        params = {
            "stationDn": plant_id,
            "clientTime": round(time.time() * 1000),
            "timeZone": 1,
            "_": round(time.time() * 1000),
        }

        r = self._session.get(url=url, params=params)
        r.raise_for_status()

        # errors in decoding the object generally mean that the login expired
        # this is handeled by @logged_in
        power_obj = r.json()

        if "data" not in power_obj:
            raise FusionSolarException("Failed to retrieve plant data.")

        return power_obj["data"]


def get_plant_stats_yearly(
        self, plant_id: str, query_time: int = None
    ) -> dict:
        """Retrieves the complete plant usage statistics for the current day.
        :param plant_id: The plant's id
        :type plant_id: str
        :param query_time: If set, must be set to 00:00:00 of the day the data should
                           be fetched for. If not set, retrieves the data for the
                           current day.
        :type query_time: int
        :return: _description_
        """
        # set the query time to today
        if not query_time:
            query_time = self._get_day_start_sec()
            
        r = self._session.get(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
            params={
                "stationDn": plant_id,
                "timeDim": 6,
                "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
                # dateTime=2024-03-07 00:00:00
                "timeZone": 2,  # 1 in no daylight
                "timeZoneStr": "Europe/Vienna",
                "_": round(time.time() * 1000),
            },
        )
        r.raise_for_status()
        plant_data = r.json()

        if not plant_data["success"] or "data" not in plant_data:
            raise FusionSolarException(
                f"Failed to retrieve plant status for {plant_id}"
            )

        # return the plant data
        return plant_data["data"]
        
def get_plant_stats_monthly(
        self, plant_id: str, query_time: int = None
    ) -> dict:
        """Retrieves the complete plant usage statistics for the current day.
        :param plant_id: The plant's id
        :type plant_id: str
        :param query_time: If set, must be set to 00:00:00 of the day the data should
                           be fetched for. If not set, retrieves the data for the
                           current day.
        :type query_time: int
        :return: _description_
        """
        # set the query time to today
        if not query_time:
            query_time = self._get_day_start_sec()
            
        r = self._session.get(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
            params={
                "stationDn": plant_id,
                "timeDim": 5,
                "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
                # dateTime=2024-03-07 00:00:00
                "timeZone": 2,  # 1 in no daylight
                "timeZoneStr": "Europe/Vienna",
                "_": round(time.time() * 1000),
            },
        )
        r.raise_for_status()
        plant_data = r.json()

        if not plant_data["success"] or "data" not in plant_data:
            raise FusionSolarException(
                f"Failed to retrieve plant status for {plant_id}"
            )

        # return the plant data
        return plant_data["data"]


def get_power_status(self) -> PowerStatus:
        """Retrieve the current power status. This is the complete
           summary accross all stations.
        :return: The current status as a PowerStatus object
        """

        url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/total-real-kpi"
        params = {
            "queryTime": round(time.time() * 1000),
            "timeZone": 1,
            "_": round(time.time() * 1000),
        }

        r = self._session.get(url=url, params=params)
        r.raise_for_status()

        # errors in decoding the object generally mean that the login expired
        # this is handeled by @logged_in
        power_obj = r.json()

        power_status = PowerStatus(
            current_power_kw=float( power_obj["data"]["currentPower"] ),
            energy_today_kwh=float( power_obj["data"]["dailyEnergy"] ),
            energy_kwh=float( power_obj["data"]["cumulativeEnergy"] ),
        )

        return power_status

def get_plant_stats(
    self, plant_id: str, query_time: int = None
) -> dict:
    """Retrieves the complete plant usage statistics for the current day.
    :param plant_id: The plant's id
    :type plant_id: str
    :param query_time: If set, must be set to 00:00:00 of the day the data should
                       be fetched for. If not set, retrieves the data for the
                       current day.
    :type query_time: int
    :return: _description_
    """
    # set the query time to today
    if not query_time:
        query_time = self._get_day_start_sec()

    r = self._session.get(
        url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
        params={
            "stationDn": plant_id,
            "timeDim": 2,
            "queryTime": query_time, # TODO: this may have changed to micro-seconds ie. timestamp * 1000
            # dateTime=2024-03-07 00:00:00
            "timeZone": 2,  # 1 in no daylight
            "timeZoneStr": "Europe/Vienna",
            "_": round(time.time() * 1000),
        },
    )
    r.raise_for_status()
    plant_data = r.json()

    if not plant_data["success"] or "data" not in plant_data:
        raise FusionSolarException(
            f"Failed to retrieve plant status for {plant_id}"
        )

    # return the plant data
    return plant_data["data"]

error_messages = {
            1: "Instalação Desligada",
            2: "Sem Consumo",
            3: "Sem Produção",
            4: "Erro de Comunicação"
        }


def process_account(account):
    USER, PASSWORD, SUBDOMAIN = account
    result = {
        "production": 0.0,
        "consumption": 0.0,
        "grid": 0.0,
        "plants": 0,
        "statuses": [],
        "alerts": [],
        "summed_production": None,
        "summed_consumption": None,
        "summed_self_consumption": None,
        "summed_overflow": None,
    }

    try:
        print(f"🔑 Logging in as {USER}...")
        client = FusionSolarClient(USER, PASSWORD, huawei_subdomain=SUBDOMAIN)
        print("Login bem-sucedido! ✅")

        plants = client.get_station_list()
        if not plants:
            print(f"⚠️ Nenhuma instalação encontrada para {USER}")
            client.log_out()
            return result

        number_plants = len(plants)
        installed_capacity_map = {p["name"]: float(p["installedCapacity"]) for p in plants}

        for i, plant in enumerate(plants, start=1):
            plant_id = plant['dn']
            plant_name = plant["name"]
            installed_capacity = installed_capacity_map.get(plant_name, 0)

            print(f"A analisar instalação...{i}/{number_plants}")
            plant_stats = client.get_plant_stats(plant_id)
            plant_data = client.get_last_plant_data(plant_stats)

            production_power = float(plant_data['productPower']['value'] or 0)
            consumption_power = float(plant_data['usePower']['value'] or 0)
            grid_power = float(plant_data['meterActivePower']['value'] or 0)

            # totals
            result["production"] += production_power
            result["consumption"] += consumption_power
            result["grid"] += grid_power
            result["plants"] += 1

            # status
            if plant['plantStatus'] == 'connected' and production_power != 0 and consumption_power != 0:
                status_icon = "🟢"
                error_state = 0
            elif plant['plantStatus'] == 'disconnected':
                status_icon = "🟡"
                error_state = 1
            elif plant['plantStatus'] == 'connected' and production_power != 0 and consumption_power == 0:
                status_icon = "🟡"
                error_state = 2
            elif plant['plantStatus'] == 'connected' and production_power == 0:
                status_icon = "🟡"
                error_state = 3
            else:
                status_icon = "🟡"
                error_state = 4

            plant_working_map = {name: code for name, code in list_of_plants}
            if error_state != 0:
                error_message = error_messages.get(error_state, "Erro desconhecido")
                if plant_working_map.get(plant_name) == "1":
                    status_icon = "⏳"
                result["alerts"].append(f"{status_icon} {plant_name} - {error_message}")

            surplus_power = max(production_power - consumption_power, 0)

            result["statuses"].append({
                "name": plant['name'],
                "pinstalled": installed_capacity,
                "production": production_power,
                "consumption": consumption_power,
                "grid": grid_power,
                "surplus": surplus_power,
                "status_icon": status_icon
            })

            # chart data
            product_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('productPower', [])]
            consumption_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('usePower', [])]
            self_use_power_filtered = [float(x) if x != '--' else 0 for x in plant_stats.get('selfUsePower', [])]

            if result["summed_production"] is None:
                result["summed_production"] = [0] * len(product_power_filtered)
                result["summed_consumption"] = [0] * len(consumption_power_filtered)
                result["summed_self_consumption"] = [0] * len(self_use_power_filtered)
                result["summed_overflow"] = [0] * len(product_power_filtered)

            result["summed_production"] = [
                round(s + c, 2) for s, c in zip(result["summed_production"], product_power_filtered)
            ]
            result["summed_consumption"] = [
                round(s + c, 2) for s, c in zip(result["summed_consumption"], consumption_power_filtered)
            ]
            result["summed_self_consumption"] = [
                round(s + c, 2) for s, c in zip(result["summed_self_consumption"], self_use_power_filtered)
            ]
            result["summed_overflow"] = [
                round(s + max(prod - cons, 0), 2)
                for s, prod, cons in zip(result["summed_overflow"], product_power_filtered, consumption_power_filtered)
            ]

        client.log_out()
        return result

    except Exception as e:
        print(f"Erro no processamento da conta {USER}: {e}")
        return result
        
@app.route("/api/live-data")
def live_data():
    try:
        total_production = total_consumption = total_grid = total_plants = 0
        statuses = []
        zero_production_plants = []
        summed_production = summed_consumption = summed_self_consumption = summed_overflow = None

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_account, acc) for acc in accounts]
            for f in as_completed(futures):
                r = f.result()
                total_production += r["production"]
                total_consumption += r["consumption"]
                total_grid += r["grid"]
                total_plants += r["plants"]
                statuses.extend(r["statuses"])
                zero_production_plants.extend(r["alerts"])

                # merge charts
                if r["summed_production"] is not None:
                    if summed_production is None:
                        summed_production = r["summed_production"]
                        summed_consumption = r["summed_consumption"]
                        summed_self_consumption = r["summed_self_consumption"]
                        summed_overflow = r["summed_overflow"]
                    else:
                        summed_production = [a + b for a, b in zip(summed_production, r["summed_production"])]
                        summed_consumption = [a + b for a, b in zip(summed_consumption, r["summed_consumption"])]
                        summed_self_consumption = [a + b for a, b in zip(summed_self_consumption, r["summed_self_consumption"])]
                        summed_overflow = [a + b for a, b in zip(summed_overflow, r["summed_overflow"])]

        alert_message = "✅ Todas as instalações estão a funcionar normalmente."
        if zero_production_plants:
            zero_production_plants.sort(key=lambda x: x.startswith("⏳"))
            alert_message = "As seguintes instalações estão com problemas:\n" + "\n".join([f"- {p}" for p in zero_production_plants])

        current_time = datetime.now().strftime('%H:%M')
        x_axis = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0, 60, 5)]
        filtered_axis = [t for t in x_axis if t <= current_time]
        n = len(filtered_axis)

        if summed_production:
            summed_production = summed_production[:n]
            summed_consumption = summed_consumption[:n]
            summed_self_consumption = summed_self_consumption[:n]
            summed_overflow = summed_overflow[:n]

        return jsonify({
            "production": round(total_production, 2),
            "consumption": round(total_consumption, 2),
            "grid": round(total_grid, 2),
            "total_plants": total_plants,
            "statuses": statuses,
            "alert": alert_message,
            "chart": {
                "x_axis": filtered_axis,
                "production": summed_production,
                "consumption": summed_consumption,
                "self_consumption": summed_self_consumption,
                "surplus": summed_overflow
            },
            "alerts": zero_production_plants
        })

    except Exception as e:
        print(f"Erro no endpoint: {e}")
        return jsonify({"error": "Erro ao carregar dados 😞"}), 500

if __name__ == "__main__":
    app.run(debug=True)



