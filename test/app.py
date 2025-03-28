from flask import Flask, render_template, request, jsonify, make_response
from flask_socketio import SocketIO, join_room, leave_room, emit
import random
import string
import secrets
import threading
import time
from flask_cors import CORS

from game import Unogame

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

rooms = {} # {'ROOMID' : ['playername1','playername1']}
sessions = {} # {'7c40fd705e1511751f6fbf5dd94936c7': {'username': 'player1', 'room_code': 'ANOLXK'}}
user_sockets = {} # {'_41gysDDBbyMJtXhAAAB': '7c40fd705e1511751f6fbf5dd94936c7'}
disconnect_timers = {}

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def generate_session_token():
    return secrets.token_hex(16)

def start_thread(token, username, room_code):
        stop_event = threading.Event()
        thread = threading.Thread(target=delayed_removal, args=(token, stop_event, username, room_code))
        disconnect_timers[token] = (thread, stop_event)
        thread.start()

def stop_thread(token):
    if token in disconnect_timers:
        print(f"Stopping thread {token}...")
        disconnect_timers[token][1].set()  # Set the stop event
        disconnect_timers[token][0].join()  # Wait for the thread to finish
        del disconnect_timers[token]
    else:
        print(f"Thread {token} not found")

def delayed_removal(token, stop_event, username, room_code):
    print(f"Thread {token} started")
    for _ in range(30):  # Check every second for 30 seconds
        if stop_event.is_set():
            print(f"User {username} rejoined, skipping removal.")
            return
        time.sleep(1)
        
    # Check again before deleting
    if room_code in rooms and username in rooms[room_code]['players']:
        rooms[room_code]['players'].remove(username)

        if not rooms[room_code]['players']:
            del rooms[room_code]

    if token in sessions:
        del sessions[token]

    print(f"User {username} permanently removed after 30 sec of inactivity.")
    print(rooms)
    if room_code in rooms:                                
        socketio.emit("update_players", {"players": rooms.get(room_code, [])}, room=room_code)
    print(f"Thread {token} stopped")

    if rooms[room_code]['started'] == True:
        print("Deleted Room")
        del rooms[room_code]

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/create_room', methods=['POST'])
def create_room():
    data = request.get_json()
    player_name = data.get('username')
    room_code = generate_room_code()
    session_token = generate_session_token()

    if room_code not in rooms:
        rooms[room_code] = {'players': [], 'started': False}
    
    rooms[room_code]['players'].append(player_name)
    sessions[session_token] = {'username': player_name, 'room_code': room_code}
    print(sessions)
    response = make_response(jsonify({'room_code': room_code, 'session_token': session_token}))
    return response

@app.route('/join_room', methods=['POST'])
def join_room_route():
    data = request.json
    room_code = data.get('room_code')
    username = data.get('username')

    if room_code in rooms:
        if rooms[room_code]['started']:
            return jsonify({'status': 'game_started'})
        
        if username in rooms[room_code]['players']:  
            return jsonify({'status': 'duplicate'})
        
        session_token = generate_session_token()
        rooms[room_code]['players'].append(username)
        sessions[session_token] = {'username': username, 'room_code': room_code}
        print(sessions)
        response = make_response(jsonify({'status': 'joined', 'session_token': session_token}))
        return response
    else:
        return jsonify({'status': 'room_not_found'})   
@app.route('/createRoom')
def createRoom():
    return render_template('createRoom.html')

@app.route('/joinRoom')
def joinRoom():
    return render_template('joinRoom.html')

@app.route('/room/<room_code>')
def room(room_code):
    if room_code in rooms:
        return render_template('room.html', room_code=room_code)
    else:
        return "Room not found", 404
    
@app.route('/get_username', methods=['POST'])
def get_username():
    data = request.get_json()
    session_token = data.get('session_token')

    if session_token in sessions:
        return jsonify({'status': 'success', 'username': sessions[session_token]['username']})
    else:
        return jsonify({'status': 'invalid'})

@app.route('/start_game', methods=['POST'])
def start_game():
    data = request.json
    room_code = data.get('room_code')
    username = data.get('username')

    if room_code in rooms and rooms[room_code]['players'][0] == username:
        if len(rooms[room_code]['players']) >= 2:
            rooms[room_code]['started'] = True

            game = Unogame(len(rooms[room_code]['players']), *rooms[room_code]['players'])
            player_hands = {player: game.get_player_hand(player) for player in rooms[room_code]['players']}

            # Emit each player's hand only to them
            for sid, session_token in user_sockets.items():
                if session_token in sessions:
                    player_name = sessions[session_token]['username']
                    if player_name in player_hands:
                        socketio.emit("your_hand", {"hand": player_hands[player_name]}, room=sid)

            socketio.emit("game_started", {}, room=room_code)
            return jsonify({'status': 'started'})
        return jsonify({'status': 'not_enough_players'})

    return jsonify({'status': 'unauthorized'})

@socketio.on("join_room")
def handle_join_room(data):
    room_code = data.get("room")
    username = data.get("username")
    session_token = data.get("session")

    print(session_token)
    print(user_sockets)
    print(sessions)
    print(rooms)       

    if room_code in rooms and not rooms[room_code]['started']:
        if username not in rooms[room_code]['players']:
            rooms[room_code]['players'].append(username)

    if session_token in disconnect_timers:
        stop_thread(session_token)
        print(f"User {username} rejoined within 30 sec. Canceling removal.")

    sessions[session_token] = {'username': username, 'room_code': room_code}
    user_sockets[request.sid] = session_token

    all_session_tokens = list(user_sockets.values())

    dublicate = 0

    for i in all_session_tokens:
        if session_token == i:
            dublicate += 1

    if dublicate >= 2:
        index_not_to_del = len(all_session_tokens) - 1 - all_session_tokens[::-1].index(session_token)
        for i, token in enumerate(all_session_tokens):
            if token == session_token and i != index_not_to_del:
                index_to_del = i
                token_to_delete = list(user_sockets.keys())[index_to_del]       
                del user_sockets[token_to_delete]       
    join_room(room_code)

    print(user_sockets)
    print(sessions)
    print(rooms)
    emit("update_players", {"players": rooms[room_code]['players']}, room=room_code)

@socketio.on("leave_room")
def handle_leave_room(data):
    room_code = data.get("room")
    username = data.get("username")
    session_token = data.get("session")

    if room_code in rooms:
        # If the game has started, delete the entire room and all sessions
        if rooms[room_code]['started']:
            print(f"Game in {room_code} was active, deleting room and clearing all players' sessions.")
            for player in rooms[room_code]['players']:
                for token, session_data in list(sessions.items()):
                    if session_data["username"] == player:
                        del sessions[token]  # Remove all player sessions
            del rooms[room_code]  # Delete the room
            emit("room_deleted", {"message": "Game ended as a player left"}, room=room_code)
            return  # Exit function early since room is deleted

    if room_code in rooms and username in rooms[room_code]['players']:
        rooms[room_code]['players'].remove(username)

        if session_token in sessions:
            del sessions[session_token]

        # If room is empty, delete it
        if not rooms[room_code]['players']:  
            del rooms[room_code]

    print("Updated Sessions:", sessions)
    print("Updated Rooms:", rooms)
    leave_room(room_code)
    print(rooms)
    emit("update_players", {"players": rooms.get(room_code, [])}, room=room_code)
    
@socketio.on("connect")
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    print(f"Client transport close disconnected. SID: {sid}")

    if sid not in user_sockets:
        print(f"Socket ID {sid} not found in active sessions. Possible early disconnect.")
        return

    session_token = user_sockets.pop(sid, None)

    if not session_token or session_token not in sessions:
        print(f"Session token {session_token} not found or invalid.")
        return

    user_data = sessions.get(session_token, {})
    username = user_data.get("username")
    room_code = user_data.get("room_code")    
        
    if not username or not room_code:
        print("Invalid user data found, skipping cleanup.")
        return
    
    if room_code in rooms:
        if rooms[room_code]['players'][0] == username and rooms[room_code]['started'] == False:
            print("Room leader left, so deleting room")
            del rooms[room_code]
            return
    else:
        del sessions[session_token]
        print("Room leader left, so no room left")
        return   

    start_thread(session_token, username, room_code)

    print(f"User {username} disconnected. Waiting 30 sec before removal.")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
