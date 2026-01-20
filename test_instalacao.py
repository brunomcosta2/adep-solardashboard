# -*- coding: utf-8 -*-
"""
Script de testes reutilizável para qualquer instalação
Faz todas as chamadas possíveis à API e guarda cada resultado num ficheiro JSON

CONFIGURAÇÃO:
    Crie um ficheiro .env na raiz do projeto com as credenciais:
    
    Formato para múltiplas contas (recomendado):
    ACCOUNT_1_USER=username1
    ACCOUNT_1_PASSWORD=password1
    ACCOUNT_1_SUBDOMAIN=subdomain1
    ACCOUNT_2_USER=username2
    ACCOUNT_2_PASSWORD=password2
    ACCOUNT_2_SUBDOMAIN=subdomain2
    ...
    
    O script tentará cada conta até encontrar a instalação.
    
    Instale python-dotenv: pip install python-dotenv

USO:
    python test_instalacao.py "Nome da Instalação"
    
    Exemplos:
    python test_instalacao.py "Escola EB1 Agra do Amial"
    python test_instalacao.py "Oficinas Domus"
    
    Se não fornecer o nome, será usado o valor do .env (PLANT_NAME) ou o padrão.

O script irá:
    1. Fazer login na conta especificada
    2. Procurar a instalação pelo nome
    3. Executar todas as chamadas possíveis à API
    4. Guardar cada resultado num ficheiro JSON na pasta test_results/

Cada ficheiro contém:
    - timestamp: Quando foi executado
    - metadata: Informação sobre o método chamado
    - data: Os dados retornados pela API (ou erro se falhou)

Os ficheiros são nomeados com timestamp para evitar sobreposições.
"""
import sys
import io
import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# Set UTF-8 encoding for stdout/stderr to handle emojis on Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fusion_solar_py.client import FusionSolarClient
from fusion_solar_py.exceptions import FusionSolarException
import time

# Tentar importar python-dotenv
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("⚠️  python-dotenv não está instalado. Instale com: pip install python-dotenv")
    print("   Continuando sem suporte a .env...")

# Monkey-patch: Adicionar métodos que são usados no app.py mas não existem no cliente original
def custom_get_station_list(self) -> list:
    """Get all stations with pagination support"""
    all_stations = []
    page_size = 50
    cur_page = 1
    
    while True:
        r = self._session.post(
            url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/station/station-list",
            json={
                "curPage": cur_page,
                "pageSize": page_size,
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
        
        stations = obj_tree["data"]["list"]
        if not stations:  # No more stations
            break
            
        all_stations.extend(stations)
        
        # Check if there are more pages
        total = obj_tree["data"].get("total", 0)
        total_pages = obj_tree["data"].get("pageCount", 0)
        
        # If we got fewer stations than page_size, we're on the last page
        if len(stations) < page_size:
            break
            
        # If total_pages is provided and we've reached it, stop
        if total_pages > 0 and cur_page >= total_pages:
            break
            
        # If we've fetched all stations based on total count, stop
        if total > 0 and len(all_stations) >= total:
            break
            
        cur_page += 1
    
    return all_stations

def get_plant_stats_monthly(self, plant_id: str, query_time: int = None) -> dict:
    """Retrieves the complete plant usage statistics for the current month.
    :param plant_id: The plant's id
    :type plant_id: str
    :param query_time: If set, must be set to 00:00:00 of the day the data should
                       be fetched for. If not set, retrieves the data for the
                       current day.
    :type query_time: int
    :return: Plant statistics data
    """
    # set the query time to today
    if not query_time:
        query_time = self._get_day_start_sec()
        
    r = self._session.get(
        url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
        params={
            "stationDn": plant_id,
            "timeDim": 5,
            "queryTime": query_time,
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

def get_plant_stats_yearly(self, plant_id: str, query_time: int = None) -> dict:
    """Retrieves the complete plant usage statistics for the current year.
    :param plant_id: The plant's id
    :type plant_id: str
    :param query_time: If set, must be set to 00:00:00 of the day the data should
                       be fetched for. If not set, retrieves the data for the
                       current day.
    :type query_time: int
    :return: Plant statistics data
    """
    # set the query time to today
    if not query_time:
        query_time = self._get_day_start_sec()
        
    r = self._session.get(
        url=f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/web/station/v1/overview/energy-balance",
        params={
            "stationDn": plant_id,
            "timeDim": 6,
            "queryTime": query_time,
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

# Método para obter alertas de uma instalação específica
def get_plant_alarm_data(self, plant_id: str) -> dict:
    """Retrieves alarm data for a specific plant
    :param plant_id: The plant's id (stationDn)
    :type plant_id: str
    :return: Alarm data for the plant
    :rtype: dict
    """
    url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/pvms/fm/v1/query"
    request_data = {
        "dataType": "CURRENT",
        "domainType": "OC_SOLAR",
        "pageNo": 1,
        "pageSize": 100,  # Aumentar para obter mais alertas
        "nativeMeDn": plant_id  # Usar plant_id em vez de device_dn
    }
    r = self._session.post(url=url, json=request_data)
    r.raise_for_status()
    return r.json()

# Método para obter dispositivos de uma instalação específica
def get_device_ids_for_plant(self, plant_id: str) -> list:
    """Gets devices associated to a specific plant
    :param plant_id: The plant's id (stationDn)
    :type plant_id: str
    :return: List of devices with type and deviceDn
    :rtype: list
    """
    url = f"https://{self._huawei_subdomain}.fusionsolar.huawei.com/rest/neteco/web/config/device/v1/device-list"
    params = {
        "conditionParams.parentDn": plant_id,  # Use plant_id instead of company_id
        "conditionParams.mocTypes": "20814,20815,20816,20819,20822,50017,60066,60014,60015,23037",
        "_": round(time.time() * 1000),
    }
    r = self._session.get(url=url, params=params)
    r.raise_for_status()
    device_data = r.json()

    devices = []
    for device in device_data.get("data", []):
        devices.append(dict(type=device.get("mocTypeName", "Unknown"), deviceDn=device.get("dn")))
    return devices

# Aplicar monkey-patch
FusionSolarClient.get_station_list = custom_get_station_list
FusionSolarClient.get_plant_stats_monthly = get_plant_stats_monthly
FusionSolarClient.get_plant_stats_yearly = get_plant_stats_yearly
FusionSolarClient.get_device_ids_for_plant = get_device_ids_for_plant
FusionSolarClient.get_plant_alarm_data = get_plant_alarm_data

# Carregar variáveis de ambiente do .env se disponível
if DOTENV_AVAILABLE:
    load_dotenv()

def load_accounts_from_env():
    """
    Carrega múltiplas contas do ficheiro .env.
    
    Formato esperado no .env:
    ACCOUNT_1_USER=username1
    ACCOUNT_1_PASSWORD=password1
    ACCOUNT_1_SUBDOMAIN=subdomain1
    ACCOUNT_2_USER=username2
    ACCOUNT_2_PASSWORD=password2
    ACCOUNT_2_SUBDOMAIN=subdomain2
    ...
    
    Retorna lista de dicionários com as contas configuradas.
    """
    accounts = []
    
    if not DOTENV_AVAILABLE:
        print("❌ python-dotenv não está disponível e nenhuma conta padrão está definida. Configure suas credenciais no ficheiro .env antes de continuar os testes.")
        return [{
            "alert": "Nenhuma conta disponível: configure suas credenciais no .env antes de executar o teste."
        }]
    
    # Procurar contas numeradas (ACCOUNT_1_*, ACCOUNT_2_*, etc.)
    account_num = 1
    while True:
        user_key = f"ACCOUNT_{account_num}_USER"
        password_key = f"ACCOUNT_{account_num}_PASSWORD"
        subdomain_key = f"ACCOUNT_{account_num}_SUBDOMAIN"
        
        user = os.getenv(user_key)
        password = os.getenv(password_key)
        subdomain = os.getenv(subdomain_key)
        
        # Se não encontrar pelo menos uma das variáveis, parar
        if not (user and password and subdomain):
            break
        
        accounts.append({
            "user": user,
            "password": password,
            "subdomain": subdomain,
            "name": f"Conta {account_num}"
        })
        account_num += 1
    
    # Se não encontrou contas numeradas, tentar variáveis sem número (compatibilidade)
    if not accounts:
        if not DOTENV_AVAILABLE:
            return [{
                "alert": "Nenhuma conta disponível: configure suas credenciais no .env antes de executar o teste."
            }]
        user = os.getenv("ACCOUNT_USER")
        password = os.getenv("ACCOUNT_PASSWORD")
        subdomain = os.getenv("ACCOUNT_SUBDOMAIN")
        
        accounts.append({
            "user": user,
            "password": password,
            "subdomain": subdomain,
            "name": "Conta Padrão"
        })
    
    return accounts

# Diretório para guardar os resultados
OUTPUT_DIR = Path("test_results")
OUTPUT_DIR.mkdir(exist_ok=True)

# Path to the captcha model file
CAPTCHA_MODEL_PATH = os.path.join("models", "captcha_huawei.onnx")

def save_result(filename: str, data: dict, metadata: dict = None):
    """Guarda um resultado num ficheiro JSON"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filepath = OUTPUT_DIR / f"{timestamp}_{filename}.json"
    
    result = {
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata or {},
        "data": data
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"  ✓ Guardado: {filepath}")
    return filepath

def safe_call(func, *args, **kwargs):
    """Executa uma função de forma segura e retorna o resultado ou erro"""
    try:
        result = func(*args, **kwargs)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__}

def find_last_valid_data_timestamp(client, plant_id, plant_stats_data, device_realtime_data_list, max_days_back=30):
    """
    Encontra o timestamp da última vez que houve dados válidos.
    
    Verifica retroativamente:
    1. Arrays de plant_stats do dia atual (productPower, usePower, meterActivePower)
    2. Se não encontrar, verifica dias anteriores (até max_days_back dias)
    3. Timestamps dos dispositivos (latestTime dos sinais) - apenas se valor não for "-"
    4. Retorna o mais recente encontrado
    
    :param client: FusionSolarClient instance
    :param plant_id: ID da instalação
    :param plant_stats_data: Dados de get_plant_stats do dia atual
    :param device_realtime_data_list: Lista de dados de get_real_time_data para cada dispositivo
    :param max_days_back: Número máximo de dias para procurar retroativamente (default: 30)
    :return: dict com informações sobre o último timestamp válido
    """
    last_timestamps = []
    
    def check_plant_stats_for_valid_data(stats_data, day_offset=0):
        """Verifica arrays de plant_stats por valores válidos"""
        if not stats_data or not isinstance(stats_data, dict):
            return []
        
        found_timestamps = []
        x_axis = stats_data.get("xAxis", [])
        
        # Verificar arrays principais
        for array_name in ["productPower", "usePower", "meterActivePower", "selfUsePower"]:
            if array_name in stats_data:
                array = stats_data[array_name]
                if isinstance(array, list) and len(array) == len(x_axis):
                    # Procurar o último índice com valor válido (não "--")
                    for i in range(len(array) - 1, -1, -1):
                        value = array[i]
                        if value != "--" and value is not None:
                            try:
                                # Tentar converter para float e verificar se é > 0 ou válido
                                float_val = float(value)
                                # Aceitar valores válidos (mesmo que sejam 0, desde que não seja "--")
                                timestamp = x_axis[i] if i < len(x_axis) else None
                                if timestamp:
                                    found_timestamps.append({
                                        "source": f"plant_stats.{array_name}",
                                        "timestamp": timestamp,
                                        "value": value,
                                        "value_float": float_val,
                                        "index": i,
                                        "day_offset": day_offset
                                    })
                                    break  # Encontrou o último válido para este array
                            except (ValueError, TypeError):
                                pass
        return found_timestamps
    
    # 1. Verificar arrays de plant_stats do dia atual
    if plant_stats_data:
        found = check_plant_stats_for_valid_data(plant_stats_data, day_offset=0)
        last_timestamps.extend(found)
    
    # 2. Se não encontrou dados válidos hoje, procurar retroativamente
    # Verificar se há dados válidos (não "--" e não zero)
    has_valid_data_today = False
    if last_timestamps:
        # Verificar se algum timestamp tem valor válido (não zero)
        for ts in last_timestamps:
            if ts.get("value_float", 0) != 0:
                has_valid_data_today = True
                break
    
    if not has_valid_data_today:
        print(f"    ⏳ Nenhum dado válido encontrado hoje, a procurar retroativamente...")
        for days_back in range(1, max_days_back + 1):
            try:
                # Calcular query_time para o dia (days_back dias atrás)
                # Usar o mesmo método que _get_day_start_sec mas para o dia específico
                target_date = datetime.now() - timedelta(days=days_back)
                # Formatar como "YYYY-MM-DD 00:00:00" e converter para timestamp
                target_date_str = target_date.strftime("%Y-%m-%d 00:00:00")
                # Usar time.strptime e time.mktime como _get_day_start_sec faz
                struct_time = time.strptime(target_date_str, "%Y-%m-%d %H:%M:%S")
                # Converter para milissegundos (como _get_day_start_sec retorna)
                query_time = round(time.mktime(struct_time) * 1000)
                
                # Obter dados desse dia
                result = safe_call(client.get_plant_stats, plant_id, query_time)
                if result.get("success") and result.get("data"):
                    stats_data = result["data"]
                    found = check_plant_stats_for_valid_data(stats_data, day_offset=days_back)
                    if found:
                        # Filtrar apenas valores não-zero (dados reais)
                        valid_found = [ts for ts in found if ts.get("value_float", 0) != 0]
                        if valid_found:
                            last_timestamps.extend(valid_found)
                            print(f"    ✓ Encontrados dados válidos há {days_back} dia(s) - {valid_found[0].get('timestamp', 'N/A')}")
                            break  # Encontrou dados válidos, parar busca
                elif days_back % 7 == 0:  # Mostrar progresso a cada semana
                    print(f"    ... Procurando há {days_back} dias...")
            except Exception as e:
                # Continuar para o próximo dia mesmo se houver erro
                continue
    
    # 3. Verificar timestamps dos dispositivos (apenas se valor não for "-")
    if device_realtime_data_list:
        for device_data in device_realtime_data_list:
            if not device_data.get("success"):
                continue
            
            data = device_data.get("data", {})
            if isinstance(data, dict):
                signals = data.get("data", [])
                if isinstance(signals, list):
                    for item in signals:
                        if isinstance(item, dict) and "signals" in item:
                            for signal in item.get("signals", []):
                                if isinstance(signal, dict) and "latestTime" in signal:
                                    latest_time = signal.get("latestTime")
                                    signal_value = signal.get("value", "-")
                                    # Só considerar se o valor não for "-" ou se for um número válido
                                    if latest_time and latest_time > 0:
                                        # Verificar se o valor é válido (não "-")
                                        is_valid = False
                                        if signal_value != "-" and signal_value is not None:
                                            try:
                                                float(signal_value)
                                                is_valid = True
                                            except (ValueError, TypeError):
                                                pass
                                        
                                        # Converter timestamp Unix para datetime
                                        try:
                                            dt = datetime.fromtimestamp(latest_time)
                                            # Só adicionar se for válido OU se for o mais recente timestamp disponível
                                            if is_valid:
                                                last_timestamps.append({
                                                    "source": f"device.{signal.get('name', 'unknown')}",
                                                    "timestamp": dt.strftime("%Y-%m-%d %H:%M:%S"),
                                                    "timestamp_unix": latest_time,
                                                    "device_signal": signal.get("name"),
                                                    "value": signal_value,
                                                    "is_valid_value": True
                                                })
                                        except (ValueError, OSError):
                                            pass
    
    # Encontrar o mais recente
    if not last_timestamps:
        return {
            "found": False,
            "message": f"Nenhum dado válido encontrado (procurou até {max_days_back} dias atrás)"
        }
    
    # Ordenar por timestamp (mais recente primeiro)
    # Para timestamps Unix, usar timestamp_unix se disponível
    def get_sort_key(item):
        if "timestamp_unix" in item:
            return item["timestamp_unix"]
        # Tentar parsear timestamp string
        try:
            # Pode ser "YYYY-MM-DD HH:MM" ou "YYYY-MM-DD HH:MM:SS"
            timestamp_str = item["timestamp"]
            if len(timestamp_str) == 16:  # "YYYY-MM-DD HH:MM"
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M")
            else:  # "YYYY-MM-DD HH:MM:SS"
                dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except:
            return 0
    
    last_timestamps.sort(key=get_sort_key, reverse=True)
    most_recent = last_timestamps[0]
    
    return {
        "found": True,
        "most_recent": most_recent,
        "all_timestamps": last_timestamps[:10],  # Top 10 mais recentes
        "total_found": len(last_timestamps),
        "search_days_back": max_days_back
    }

def main():
    # Parse argumentos da linha de comandos
    parser = argparse.ArgumentParser(
        description='Script de testes para instalações Fusion Solar',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Exemplo: python test_instalacao.py "Escola EB1 Agra do Amial"'
    )
    parser.add_argument(
        'plant_name',
        nargs='?',  # Argumento opcional
        help='Nome da instalação a testar (obrigatório: defina por argumento ou pela variável de ambiente PLANT_NAME)'
    )
    
    args = parser.parse_args()
    plant_name = args.plant_name
    
    print("="*60)
    print(f"SCRIPT DE TESTES - {plant_name}")
    print("="*60)
    print()
    
    # Carregar contas do .env
    accounts = load_accounts_from_env()
    print(f"📋 Encontradas {len(accounts)} conta(s) configurada(s)")
    if DOTENV_AVAILABLE:
        print("   (Carregadas do ficheiro .env)")
    else:
        print("   (Usando valores padrão - instale python-dotenv para usar .env)")
    print()
    
    # Tentar cada conta até encontrar a instalação
    plant = None
    client = None
    used_account = None
    
    for account in accounts:
        account_name = account["name"]
        print(f"🔑 A tentar fazer login na {account_name} ({account['user']})...")
        
        client_kwargs = {"huawei_subdomain": account["subdomain"]}
        if CAPTCHA_MODEL_PATH and os.path.exists(CAPTCHA_MODEL_PATH):
            client_kwargs["captcha_model_path"] = CAPTCHA_MODEL_PATH
        
        try:
            client = FusionSolarClient(account["user"], account["password"], **client_kwargs)
            print(f"  ✓ Login bem-sucedido na {account_name}!")
        except Exception as e:
            print(f"  ❌ Erro no login na {account_name}: {e}")
            print(f"  ⏭️  A tentar próxima conta...")
            print()
            continue
        
        # Obter lista de estações desta conta
        print(f"  📋 A obter lista de estações da {account_name}...")
        result = safe_call(client.get_station_list)
        
        if not result["success"] or not result.get("data"):
            print(f"  ❌ Não foi possível obter a lista de estações da {account_name}")
            print(f"  ⏭️  A tentar próxima conta...")
            print()
            continue
        
        stations = result["data"]
        print(f"  ✓ Encontradas {len(stations)} estações na {account_name}")
        
        # Procurar a instalação específica
        for station in stations:
            if station.get("name") == plant_name:
                plant = station
                used_account = account
                break
        
        if plant:
            print(f"  ✓ Instalação '{plant_name}' encontrada na {account_name}!")
            break
        else:
            print(f"  ⚠️  Instalação '{plant_name}' não encontrada na {account_name}")
            print(f"  ⏭️  A tentar próxima conta...")
            print()
    
    # Verificar se encontrou a instalação
    if not plant:
        print(f"  ❌ Instalação '{plant_name}' não encontrada em nenhuma das contas!")
        print()
        print("  Estações disponíveis nas contas verificadas:")
        # Mostrar estações da última conta tentada
        if client:
            result = safe_call(client.get_station_list)
            if result.get("success") and result.get("data"):
                for station in result["data"][:20]:  # Mostrar até 20
                    print(f"    - {station.get('name', 'N/A')}")
                if len(result["data"]) > 20:
                    print(f"    ... e mais {len(result['data']) - 20} estações")
        return
    
    if not client:
        print("  ❌ Não foi possível fazer login em nenhuma conta!")
        return
    
    plant_id = plant.get("dn")
    print()
    print(f"  ✓ Instalação encontrada: {plant_name}")
    print(f"     Conta utilizada: {used_account['name']}")
    
    plant_id = plant.get("dn")
    print(f"  ✓ Instalação encontrada: {plant_name}")
    print(f"     ID: {plant_id}")
    print(f"     Status: {plant.get('plantStatus', 'N/A')}")
    print(f"     Capacidade instalada: {plant.get('installedCapacity', 'N/A')} kW")
    print()
    
    # Guardar dados completos da estação
    save_result("02_plant_info", {
        "plant": plant,
        "all_stations": stations
    }, {
        "method": "get_station_list (filtered)",
        "description": "Informação completa da instalação e todas as estações"
    })
    
    # 2. Status geral de potência
    print("2️⃣  A obter status geral de potência...")
    result = safe_call(client.get_power_status)
    save_result("03_power_status", result, {
        "method": "get_power_status",
        "description": "Status geral de potência de todas as estações"
    })
    if result["success"]:
        ps = result["data"]
        print(f"  ✓ Potência atual: {ps.current_power_kw} kW")
        print(f"     Energia hoje: {ps.energy_today_kwh} kWh")
        print(f"     Energia total: {ps.energy_kwh} kWh")
    print()
    
    # 3. Dados atuais da planta
    print("3️⃣  A obter dados atuais da planta...")
    result = safe_call(client.get_current_plant_data, plant_id)
    save_result("04_current_plant_data", result, {
        "method": "get_current_plant_data",
        "plant_id": plant_id,
        "description": "Dados em tempo real da instalação"
    })
    if result["success"]:
        print(f"  ✓ Dados obtidos com sucesso")
        # Mostrar algumas chaves importantes
        data = result["data"]
        if isinstance(data, dict):
            print(f"     Chaves disponíveis: {', '.join(list(data.keys())[:10])}")
    print()
    
    # 4. Estatísticas do dia
    print("4️⃣  A obter estatísticas do dia...")
    result = safe_call(client.get_plant_stats, plant_id)
    save_result("05_plant_stats_daily", result, {
        "method": "get_plant_stats",
        "plant_id": plant_id,
        "time_dim": 2,
        "description": "Estatísticas do dia (intervalos de 5 minutos)"
    })
    plant_stats_data = None
    if result["success"]:
        plant_stats_data = result["data"]
        if isinstance(plant_stats_data, dict):
            print(f"  ✓ Estatísticas obtidas")
            print(f"     Chaves disponíveis: {', '.join(list(plant_stats_data.keys())[:10])}")
            # Mostrar tamanho dos arrays
            for key in ["productPower", "usePower", "selfUsePower"]:
                if key in plant_stats_data and isinstance(plant_stats_data[key], list):
                    print(f"     {key}: {len(plant_stats_data[key])} valores")
    print()
    
    # 4b. Últimos dados com timestamps (atualizações recentes)
    if plant_stats_data:
        print("4️⃣b A obter últimos dados com timestamps (atualizações recentes)...")
        result = safe_call(client.get_last_plant_data, plant_stats_data)
        save_result("05b_last_plant_data", result, {
            "method": "get_last_plant_data",
            "plant_id": plant_id,
            "description": f"Últimos dados com timestamps da instalação {plant_name} - mostra quando foi a última atualização de cada métrica"
        })
        if result["success"]:
            last_data = result["data"]
            if isinstance(last_data, dict):
                print(f"  ✓ Últimos dados extraídos")
                # Mostrar alguns timestamps importantes
                for key in ["productPower", "usePower", "meterActivePower"]:
                    if key in last_data and isinstance(last_data[key], dict):
                        timestamp = last_data[key].get("time", "N/A")
                        value = last_data[key].get("value", "N/A")
                        print(f"     {key}: {value} (última atualização: {timestamp})")
        print()
    
    # 5. Estatísticas mensais
    print("5️⃣  A obter estatísticas mensais...")
    result = safe_call(client.get_plant_stats_monthly, plant_id)
    save_result("06_plant_stats_monthly", result, {
        "method": "get_plant_stats_monthly",
        "plant_id": plant_id,
        "time_dim": 5,
        "description": "Estatísticas mensais"
    })
    if result["success"]:
        data = result["data"]
        if isinstance(data, dict):
            print(f"  ✓ Estatísticas mensais obtidas")
            print(f"     Chaves disponíveis: {', '.join(list(data.keys())[:10])}")
    print()
    
    # 6. Estatísticas anuais
    print("6️⃣  A obter estatísticas anuais...")
    result = safe_call(client.get_plant_stats_yearly, plant_id)
    save_result("07_plant_stats_yearly", result, {
        "method": "get_plant_stats_yearly",
        "plant_id": plant_id,
        "time_dim": 6,
        "description": "Estatísticas anuais"
    })
    if result["success"]:
        data = result["data"]
        if isinstance(data, dict):
            print(f"  ✓ Estatísticas anuais obtidas")
            print(f"     Chaves disponíveis: {', '.join(list(data.keys())[:10])}")
    print()
    
    # 7. Fluxo da planta
    print("7️⃣  A obter fluxo da planta...")
    result = safe_call(client.get_plant_flow, plant_id)
    save_result("08_plant_flow", result, {
        "method": "get_plant_flow",
        "plant_id": plant_id,
        "description": "Fluxo de energia da planta (retorna flow_data completo)"
    })
    if result["success"]:
        data = result["data"]
        if isinstance(data, dict):
            print(f"  ✓ Fluxo obtido")
            # get_plant_flow retorna o objeto completo, não só data
            if "data" in data:
                print(f"     Chaves em data: {', '.join(list(data['data'].keys())[:10])}")
            print(f"     Chaves principais: {', '.join(list(data.keys())[:10])}")
    print()
    
    # 8. IDs dos dispositivos da instalação específica
    print("8️⃣  A obter IDs dos dispositivos da instalação...")
    result = safe_call(client.get_device_ids_for_plant, plant_id)
    save_result("09_device_ids", result, {
        "method": "get_device_ids_for_plant",
        "plant_id": plant_id,
        "description": f"Lista de IDs dos dispositivos da instalação {plant_name} (retorna lista de dicts com type e deviceDn)"
    })
    device_ids = []
    device_list = []
    if result["success"]:
        device_list = result["data"] or []
        # get_device_ids_for_plant retorna lista de dicts: [{"type": "...", "deviceDn": "..."}]
        if device_list and isinstance(device_list[0], dict):
            device_ids = [d.get("deviceDn") for d in device_list if d.get("deviceDn")]
        else:
            device_ids = device_list if device_list else []
        print(f"  ✓ Encontrados {len(device_list)} dispositivos na instalação {plant_name}")
        if device_list:
            for i, device in enumerate(device_list[:10], 1):  # Mostrar até 10
                if isinstance(device, dict):
                    print(f"     {i}. {device.get('type', 'N/A')}: {device.get('deviceDn', 'N/A')}")
                else:
                    print(f"     {i}. {device}")
    else:
        print(f"  ⚠️  Erro ao obter dispositivos: {result.get('error', 'Unknown error')}")
    print()
    
    # 9. IDs das plantas
    print("9️⃣  A obter IDs das plantas...")
    result = safe_call(client.get_plant_ids)
    save_result("10_plant_ids", result, {
        "method": "get_plant_ids",
        "description": "Lista de IDs de todas as plantas"
    })
    if result["success"]:
        plant_ids = result["data"]
        print(f"  ✓ Encontradas {len(plant_ids)} plantas")
    print()
    
    # 10. Dados em tempo real dos dispositivos
    device_realtime_results = []
    if device_ids:
        print("🔟 A obter dados em tempo real dos dispositivos...")
        for i, device_id in enumerate(device_ids[:3], 1):  # Limitar a 3 para não ser demasiado
            device_info = device_list[i-1] if (device_list and i-1 < len(device_list)) else {}
            device_type = device_info.get('type', 'N/A') if isinstance(device_info, dict) else 'N/A'
            print(f"    Dispositivo {i}/{min(3, len(device_ids))}: {device_type} ({device_id})")
            result = safe_call(client.get_real_time_data, device_id)
            device_realtime_results.append(result)
            save_result(f"11_realtime_data_device_{i}", result, {
                "method": "get_real_time_data",
                "device_id": device_id,
                "device_type": device_type,
                "description": f"Dados em tempo real do dispositivo {device_type} ({device_id})"
            })
        print()
    
    # 10b. Análise: Última vez que houve dados válidos (procura retroativamente)
    # Nota: plant_stats_data foi definido na secção 4
    print("🔟b A analisar última vez que houve dados válidos (procurando retroativamente)...")
    # Usar plant_stats_data da secção 4 (definido acima)
    # Procurar até 30 dias atrás se necessário
    last_valid_analysis = find_last_valid_data_timestamp(
        client, 
        plant_id, 
        plant_stats_data, 
        device_realtime_results,
        max_days_back=30
    )
    save_result("11b_last_valid_data_analysis", last_valid_analysis, {
        "method": "find_last_valid_data_timestamp",
        "plant_id": plant_id,
        "description": "Análise para encontrar o timestamp da última vez que houve dados válidos"
    })
    if last_valid_analysis.get("found"):
        most_recent = last_valid_analysis["most_recent"]
        print(f"  ✓ Último dado válido encontrado:")
        print(f"     Fonte: {most_recent.get('source', 'N/A')}")
        print(f"     Timestamp: {most_recent.get('timestamp', 'N/A')}")
        if 'value' in most_recent:
            print(f"     Valor: {most_recent.get('value', 'N/A')}")
        print(f"     Total de timestamps encontrados: {last_valid_analysis.get('total_found', 0)}")
    else:
        print(f"  ⚠️  {last_valid_analysis.get('message', 'Nenhum dado válido encontrado')}")
    print()
    
    # 11. Dados de alarmes da instalação
    print("1️⃣1️⃣  A obter dados de alarmes da instalação...")
    result = safe_call(client.get_plant_alarm_data, plant_id)
    save_result("12_plant_alarm_data", result, {
        "method": "get_plant_alarm_data",
        "plant_id": plant_id,
        "description": f"Dados de alarmes da instalação {plant_name}"
    })
    if result["success"]:
        data = result["data"]
        if isinstance(data, dict):
            total_count = data.get("data", {}).get("totalCount", 0)
            print(f"  ✓ Encontrados {total_count} alertas na instalação")
    print()
    
    # 11b. Dados de alarmes por dispositivo (se disponível)
    if device_ids:
        print("1️⃣1️⃣b A obter dados de alarmes por dispositivo...")
        for i, device_id in enumerate(device_ids[:3], 1):  # Limitar a 3
            device_info = device_list[i-1] if (device_list and i-1 < len(device_list)) else {}
            device_type = device_info.get('type', 'N/A') if isinstance(device_info, dict) else 'N/A'
            print(f"    Dispositivo {i}/{min(3, len(device_ids))}: {device_type} ({device_id})")
            result = safe_call(client.get_alarm_data, device_id)
            save_result(f"12b_alarm_data_device_{i}", result, {
                "method": "get_alarm_data",
                "device_id": device_id,
                "device_type": device_type,
                "plant_id": plant_id,
                "description": f"Dados de alarmes do dispositivo {device_type} ({device_id}) da instalação {plant_name}"
            })
        print()
    
    # 12. IDs de baterias
    print("1️⃣2️⃣  A obter IDs de baterias...")
    result = safe_call(client.get_battery_ids, plant_id)
    save_result("13_battery_ids", result, {
        "method": "get_battery_ids",
        "plant_id": plant_id,
        "description": "Lista de IDs de baterias da instalação"
    })
    battery_ids = []
    if result["success"]:
        battery_ids = result["data"]
        print(f"  ✓ Encontradas {len(battery_ids)} baterias")
    print()
    
    # 13. Status das baterias
    if battery_ids:
        print("1️⃣3️⃣  A obter status das baterias...")
        for i, battery_id in enumerate(battery_ids, 1):
            print(f"    Bateria {i}/{len(battery_ids)}: {battery_id}")
            
            # Status básico
            result = safe_call(client.get_battery_basic_stats, battery_id)
            save_result(f"14_battery_basic_{i}", result, {
                "method": "get_battery_basic_stats",
                "battery_id": battery_id,
                "description": f"Status básico da bateria {battery_id}"
            })
            
            # Status completo
            result = safe_call(client.get_battery_status, battery_id)
            save_result(f"15_battery_status_{i}", result, {
                "method": "get_battery_status",
                "battery_id": battery_id,
                "description": f"Status completo da bateria {battery_id}"
            })
            
            # Estatísticas do dia
            result = safe_call(client.get_battery_day_stats, battery_id)
            save_result(f"16_battery_day_stats_{i}", result, {
                "method": "get_battery_day_stats",
                "battery_id": battery_id,
                "description": f"Estatísticas do dia da bateria {battery_id}"
            })
        print()
    
    # 14. Dados históricos (se device_ids disponível)
    if device_ids:
        print("1️⃣4️⃣  A obter dados históricos...")
        device_dn = device_ids[0] if device_ids else None
        result = safe_call(client.get_historical_data, 
                          signal_ids=['30014', '30016', '30017'], 
                          device_dn=device_dn)
        save_result("17_historical_data", result, {
            "method": "get_historical_data",
            "device_dn": device_dn,
            "signal_ids": ['30014', '30016', '30017'],
            "description": "Dados históricos do dispositivo"
        })
        if result["success"]:
            print(f"  ✓ Dados históricos obtidos")
        print()
    
    # 15. Estatísticas de otimizadores (se disponível)
    print("1️⃣5️⃣  A obter estatísticas de otimizadores...")
    # get_optimizer_stats precisa de inverter_id, não plant_id
    # Tentar com device_ids se disponível
    if device_ids:
        for i, device_id in enumerate(device_ids[:2], 1):  # Limitar a 2
            print(f"    Dispositivo {i}/{min(2, len(device_ids))}: {device_id}")
            result = safe_call(client.get_optimizer_stats, device_id)
            save_result(f"18_optimizer_stats_device_{i}", result, {
                "method": "get_optimizer_stats",
                "inverter_id": device_id,
                "description": f"Estatísticas dos otimizadores do dispositivo {device_id}"
            })
            if result["success"]:
                print(f"      ✓ Estatísticas obtidas")
    else:
        # Tentar com plant_id mesmo assim (pode funcionar em alguns casos)
        result = safe_call(client.get_optimizer_stats, plant_id)
        save_result("18_optimizer_stats", result, {
            "method": "get_optimizer_stats",
            "inverter_id": plant_id,
            "description": "Estatísticas dos otimizadores (tentativa com plant_id)"
        })
    print()
    
    # Resumo final
    print("="*60)
    print("TESTES CONCLUÍDOS")
    print("="*60)
    print(f"📁 Resultados guardados em: {OUTPUT_DIR.absolute()}")
    print(f"📊 Total de ficheiros criados: {len(list(OUTPUT_DIR.glob('*.json')))}")
    print()
    print("💡 Dica: Analise os ficheiros JSON para ver todos os parâmetros")
    print("   disponíveis que podem ser úteis para monitorização de estados.")
    print()
    
    # Logout
    try:
        client.log_out()
        print("  ✓ Logout realizado")
    except:
        pass

if __name__ == "__main__":
    main()

