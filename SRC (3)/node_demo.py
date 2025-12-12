# p2p_blockchain_gui.py / node_demo.py
import socket
import threading
import json
import time
import tkinter as tk
from tkinter import ttk, messagebox
import platform

from block import Block
from blockchain import Blockchain

DIFFICULTY_PREFIX_ZERO = 3   # số lượng '0' đầu hash yêu cầu

# ================== CẤU HÌNH THEO MÁY ==================
# 👉 Trên MAC của bạn:
#    - MY_ZERO_TIER_IP = IP ZeroTier của MAC (10.125.45.183)
#    - BOOTSTRAP_ZERO_TIER_IP = IP ZeroTier của WINDOWS gốc (10.125.45.249)
#
# 👉 Trên máy WINDOWS gốc:
#    - MY_ZERO_TIER_IP = IP ZeroTier của chính nó (10.125.45.249)
#    - BOOTSTRAP_ZERO_TIER_IP = 10.125.45.249  (tự làm bootstrap)
MY_ZERO_TIER_IP = "10.125.45.249"          # IP ZeroTier của MAC
BOOTSTRAP_ZERO_TIER_IP = "10.125.45.249"   # IP ZeroTier WINDOWS gốc


class PeerNode:
    def __init__(self, root):
        self.root = root
        self.root.title("Blockchain P2P - Demo Chuyển Tiền")

        # --- Thông tin node ---
        self.host_ip = MY_ZERO_TIER_IP
        self.port = tk.IntVar(value=5001)

        default_name = f"{socket.gethostname()} ({platform.system()})"
        self.node_name = tk.StringVar(value=default_name)

        # Máy gốc để join
        self.bootstrap_ip = tk.StringVar(value=BOOTSTRAP_ZERO_TIER_IP)
        self.bootstrap_port = tk.IntVar(value=5001)

        # Trạng thái mạng
        self.server_socket = None
        self.running = False
        self.joined = False

        # Peers: {(ip,port): name}
        self.peers = {}

        # Blockchain (ban đầu RỖNG, không có genesis trong chains)
        self.blockchain = Blockchain()

        # Mining + consensus
        self.pending_tx = None
        self.global_mining = False
        self.is_mining = False
        self.mining_lock = threading.Lock()

        # Consensus: chỉ dùng cho block mà node này là miner
        self.current_proposed_block = None
        self.current_block_hash = None
        self.block_votes = {}          # {block_hash: set(node_id YES)}
        self.block_has_no = set()      # block_hash đã nhận ít nhất 1 vote NO

        # Dùng để chọn block có timestamp nhỏ nhất khi có nhiều proposal cùng previous_hash
        # {previous_hash: (best_timestamp, best_block_hash)}
        self.best_proposal_for_prev = {}

        # Map hash → miner để hiển thị ở bảng blockchain
        self.block_miner = {}

        #Phần thưởng Bitcoin
        self.btc = 0

        # GUI
        self.build_gui()
        self.refresh_block_table()

        # Luồng sync định kỳ
        threading.Thread(target=self.periodic_sync_loop, daemon=True).start()

    # ============= Helper =============
    def node_id(self):
        return f"{self.host_ip}:{self.port.get()}"
    
    def reward(self, length):
        return self.btc + length

    def get_self_display(self):
        return f"{self.node_name.get()} @ {self.host_ip}:{self.port.get()}"

    def log(self, text):
        """Ghi log ra khung bên phải (trắng trên nền đen)."""
        def _log():
            self.log_box.config(state="normal")
            self.log_box.insert(
                tk.END,
                f"[{time.strftime('%H:%M:%S')}] {text}\n"
            )
            self.log_box.see(tk.END)
            self.log_box.config(state="disabled")
        self.root.after(0, _log)

    def reset_round_state(self):
        self.pending_tx = None
        self.global_mining = False
        self.is_mining = False
        self.current_proposed_block = None
        self.current_block_hash = None
        self.block_votes.clear()
        self.block_has_no.clear()
        self.best_proposal_for_prev.clear()
        self.status.set("Trạng thái: Idle")

    def validate_block_pow(self, block):
        if not str(block.hash).startswith("0" * DIFFICULTY_PREFIX_ZERO):
            return False

        if not self.blockchain.chains:
            # block đầu tiên: chỉ cần PoW
            return True

        last = self.blockchain.chains[-1]
        if block.previous_hash != last.hash:
            return False

        return True

    # ============= GUI =============
    def build_gui(self):
        # cao hơn tí cho dễ nhìn phần blockchain
        self.root.geometry("1200x800")

        # ----- TOP: cấu hình node -----
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        # middle chỉ fill ngang, không expand hết chiều cao
        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.X)

        left = ttk.LabelFrame(mid, text="Peers")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=5)

        center = ttk.LabelFrame(mid, text="Giao dịch")
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        right = ttk.LabelFrame(mid, text="Logs thời gian thực")
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=5)

        # bottom chiếm phần còn lại để hiển thị blockchain
        bottom = ttk.LabelFrame(self.root, text="Blockchain")
        bottom.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)

        # ----- TOP -----
        ttk.Label(top, text="Tên:").grid(row=0, column=0)
        ttk.Entry(top, textvariable=self.node_name, width=25).grid(row=0, column=1)

        ttk.Label(top, text="IP:").grid(row=0, column=2)
        ttk.Label(top, text=self.host_ip).grid(row=0, column=3)

        ttk.Label(top, text="Port:").grid(row=0, column=4)
        ttk.Entry(top, textvariable=self.port, width=6).grid(row=0, column=5)

        self.start_btn = ttk.Button(top, text="Start Node", command=self.start_node)
        self.start_btn.grid(row=0, column=6, padx=5)

        ttk.Label(top, text="Bootstrap IP:").grid(row=1, column=0)
        ttk.Entry(top, textvariable=self.bootstrap_ip, width=15).grid(row=1, column=1)

        ttk.Label(top, text="Port:").grid(row=1, column=2)
        ttk.Entry(top, textvariable=self.bootstrap_port, width=6).grid(row=1, column=3)

        self.join_btn = ttk.Button(top, text="Join mạng", command=self.join_network)
        self.join_btn.grid(row=1, column=4)

        self.leave_btn = ttk.Button(
            top, text="Rời mạng", command=self.leave_network, state=tk.DISABLED
        )
        self.leave_btn.grid(row=1, column=5)

        self.status = tk.StringVar(value="Trạng thái: Idle")
        ttk.Label(top, textvariable=self.status, foreground="blue").grid(row=1, column=6)

        # ----- LEFT: danh sách peers -----
        self.peers_list = tk.Listbox(left, width=35)
        self.peers_list.pack(fill=tk.BOTH, expand=True)

        # ----- CENTER: form giao dịch -----
        ttk.Label(center, text="From:").grid(row=0, column=0, sticky="w")
        self.from_label = ttk.Label(
            center, text=self.get_self_display(), foreground="green"
        )
        self.from_label.grid(row=0, column=1, sticky="w")

        ttk.Label(center, text="To:").grid(row=1, column=0)
        self.to_combo = ttk.Combobox(center, state="readonly", width=40)
        self.to_combo.grid(row=1, column=1)

        ttk.Label(center, text="Amount ($):").grid(row=2, column=0)
        self.amount = tk.StringVar(value="10")
        ttk.Entry(center, textvariable=self.amount).grid(row=2, column=1)

        ttk.Label(center, text="Message:").grid(row=3, column=0)
        self.message = tk.StringVar(value="Demo payment")
        ttk.Entry(center, textvariable=self.message).grid(row=3, column=1)

        ttk.Button(center, text="GỬI", command=self.send_transaction).grid(
            row=4, column=0, columnspan=2, pady=10
        )

        # ----- RIGHT: log box -----
        self.log_box = tk.Text(
            right,
            width=50,
            height=30,
            state="disabled",
            bg="#111111",
            fg="white",
            insertbackground="white",
            wrap="word",
            font=("Consolas", 10),
        )
        self.log_box.pack(fill=tk.BOTH, expand=True)

        # ----- BOTTOM: blockchain -----
        # thêm cột MINER
        cols = ("index", "time", "miner", "data", "prev", "hash")
        self.block_tree = ttk.Treeview(bottom, columns=cols, show="headings")

        self.block_tree.heading("index", text="INDEX")
        self.block_tree.heading("time", text="TIME")
        self.block_tree.heading("miner", text="MINER")
        self.block_tree.heading("data", text="DATA")
        self.block_tree.heading("prev", text="PREV")
        self.block_tree.heading("hash", text="HASH")

        # set width mặc định, cột DATA sẽ auto chỉnh trong refresh_block_table
        self.block_tree.column("index", width=60, anchor="center")
        self.block_tree.column("time", width=80, anchor="center")
        self.block_tree.column("miner", width=220, anchor="w")
        self.block_tree.column("data", width=300, anchor="w")
        self.block_tree.column("prev", width=160, anchor="w")
        self.block_tree.column("hash", width=180, anchor="w")

        self.block_tree.pack(fill=tk.BOTH, expand=True)

        # tăng rowheight để text nhìn thoáng hơn
        style = ttk.Style()
        style.configure("Treeview", rowheight=28)

    # ============= Network =============
    def start_node(self):
        if self.joined:
            messagebox.showwarning("Info", "Đã join mạng rồi, không thể start lại.")
        if self.running:
            messagebox.showinfo("Info", "Node đang chạy.")
            return

        try:
            p = int(self.port.get())
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Lắng nghe trên tất cả interface (bao gồm ZeroTier)
            self.server_socket.bind(("", p))
            self.server_socket.listen(5)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            return

        self.running = True
        threading.Thread(target=self.accept_loop, daemon=True).start()
        self.log(f"Node started tại {self.host_ip}:{p}")

    def accept_loop(self):
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                threading.Thread(
                    target=self.handle_client, args=(conn,), daemon=True
                ).start()
            except Exception:
                break

    def handle_client(self, conn):
        try:
            data = conn.recv(8192)
            if not data:
                return
            msg = json.loads(data.decode())
            self.handle_message(msg, conn)
        except Exception as e:
            print("Lỗi handle_client:", e)
        finally:
            conn.close()

    def handle_message(self, msg, conn=None):
        t = msg.get("type")

        if t == "HELLO":
            ip, port, name = msg["ip"], msg["port"], msg["name"]
            self.add_peer(ip, port, name)
            reply = {
                "type": "WELCOME",
                "peers": self.list_peers(),
                "blockchain": self.blockchain.to_list(),
            }
            if conn:
                conn.send(json.dumps(reply).encode())
            self.broadcast({"type": "NEW_PEER", "ip": ip, "port": port, "name": name})

        elif t in ("WELCOME", "SYNC_RESPONSE"):
            for p in msg["peers"]:
                self.add_peer(p["ip"], p["port"], p["name"])
            if self.blockchain.replace_chain(msg["blockchain"]):
                self.refresh_block_table()

        elif t == "NEW_PEER":
            self.add_peer(msg["ip"], msg["port"], msg["name"])

        elif t == "LEAVE":
            key = (msg["ip"], msg["port"])
            if key in self.peers:
                self.log(f"Peer left: {self.peers[key]} @ {key[0]}:{key[1]}")
                del self.peers[key]
                self.refresh_peers()

        elif t == "NEW_TX":
            tx = msg["tx"]
            self.log(f"Nhận TX mới: {tx}")
            self.start_mining_for_tx(tx)

        elif t == "BLOCK_PROPOSAL":
            self.handle_block_proposal(msg)

        elif t == "BLOCK_VOTE":
            self.handle_block_vote(msg)

        elif t == "BLOCK_COMMIT":
            self.handle_block_commit(msg)

        elif t == "SYNC_REQUEST":
            reply = {
                "type": "SYNC_RESPONSE",
                "peers": self.list_peers(),
                "blockchain": self.blockchain.to_list(),
            }
            if conn:
                conn.send(json.dumps(reply).encode())

    # ----- Peers -----
    def add_peer(self, ip, port, name):
        key = (ip, port)
        if key == (self.host_ip, self.port.get()):
            return
        if key not in self.peers:
            self.peers[key] = name
            self.refresh_peers()
            self.log(f"Peer joined: {name} @ {ip}:{port}")

    def list_peers(self):
        arr = [
            {"ip": self.host_ip, "port": self.port.get(), "name": self.node_name.get()}
        ]
        for (ip, port), name in self.peers.items():
            arr.append({"ip": ip, "port": port, "name": name})
        return arr

    def refresh_peers(self):
        self.peers_list.delete(0, tk.END)
        values = []
        for (ip, port), name in self.peers.items():
            txt = f"{name} @ {ip}:{port}"
            self.peers_list.insert(tk.END, txt)
            values.append(txt)
        self.to_combo["values"] = values

    def join_network(self):
        if not self.running:
            messagebox.showwarning("Info", "Phải start node trước.")
            return

        ip = self.bootstrap_ip.get().strip()
        port = int(self.bootstrap_port.get())

        self.log(f"🔍 DEBUG: chuẩn bị connect tới {ip}:{port}")

        # Bootstrap tự join (trên máy bootstrap)
        if (ip, port) == (self.host_ip, self.port.get()):
            self.peers[(ip, port)] = self.node_name.get()
            self.joined = True
            self.log("Bootstrap mode: bạn là node gốc.")
            self.join_btn.config(state=tk.DISABLED)
            self.leave_btn.config(state=tk.NORMAL)
            return

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((ip, port))
            self.log("✅ TCP connect OK, gửi HELLO ...")

            hello = {
                "type": "HELLO",
                "name": self.node_name.get(),
                "ip": self.host_ip,
                "port": self.port.get(),
            }
            s.send(json.dumps(hello).encode())

            resp_raw = s.recv(8192)
            if not resp_raw:
                raise RuntimeError("Không nhận được WELCOME từ bootstrap")
            resp = json.loads(resp_raw.decode())
            self.handle_message(resp)

            self.joined = True
            self.join_btn.config(state=tk.DISABLED)
            self.leave_btn.config(state=tk.NORMAL)
            self.log("✅ Join mạng thành công")
            s.close()
        except Exception as e:
            print("Join fail:", e)
            self.log(f"❌ JOIN ERROR: {repr(e)}")
            messagebox.showerror("Error", "Join fail")

    def leave_network(self):
        self.broadcast(
            {
                "type": "LEAVE",
                "ip": self.host_ip,
                "port": self.port.get(),
                "name": self.node_name.get(),
            }
        )
        self.peers.clear()
        self.refresh_peers()
        self.joined = False
        self.leave_btn.config(state=tk.DISABLED)
        self.join_btn.config(state=tk.NORMAL)
        self.log("Đã rời mạng")
        self.reset_round_state()

    def broadcast(self, msg):
        for (ip, port), name in list(self.peers.items()):
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2)
                s.connect((ip, port))
                s.send(json.dumps(msg).encode())
                s.close()
            except Exception as e:
                print(f"[BROADCAST] FAIL tới {name} @ {ip}:{port}: {e}")

    # ============= Transaction & Mining =============
    def send_transaction(self):
        if not self.joined:
            messagebox.showwarning("Lỗi", "Phải join mạng trước.")
            return

        to = self.to_combo.get()
        if not to:
            messagebox.showwarning("Lỗi", "Chọn máy nhận")
            return

        if self.get_self_display() in to:
            messagebox.showwarning("Lỗi", "Không gửi cho chính mình")
            return

        try:
            amt = float(self.amount.get())
        except Exception:
            messagebox.showerror("Error", "Amount không hợp lệ")
            return

        peer = next(
            (
                (ip, port, name)
                for (ip, port), name in self.peers.items()
                if f"{name} @ {ip}:{port}" == to
            ),
            None,
        )
        if not peer:
            messagebox.showerror("Error", "Không tìm thấy peer nhận")
            return

        tx = {
            "from": self.get_self_display(),
            "to": f"{peer[2]} @ {peer[0]}:{peer[1]}",
            "amount": amt,
            "message": self.message.get(),
            "time": time.time(),
        }

        self.log(f"Gửi TX: {tx}")
        self.broadcast({"type": "NEW_TX", "tx": tx})
        self.start_mining_for_tx(tx)

    def start_mining_for_tx(self, tx):
        with self.mining_lock:
            if self.pending_tx is not None or self.global_mining:
                return
            self.pending_tx = tx
            self.global_mining = True

        self.log("TX mới, quá trình bắt đầu sau 5s...")
        threading.Thread(target=self._delayed_mining_start, daemon=True).start()

    def _delayed_mining_start(self):
        time.sleep(5)
        with self.mining_lock:
            if not self.global_mining or self.pending_tx is None or self.is_mining:
                return
            self.is_mining = True

        self.status.set("Đang đào block...")
        self.log("Bắt đầu đào block cho TX đang chờ.")
        self.mine_block()

    def mine_block(self):
        # Gói payload gồm: tx + miner để hiển thị ở blockchain
        payload = {
            "tx": self.pending_tx,
            "miner": self.get_self_display(),
        }
        data = json.dumps(payload, ensure_ascii=False)

        last_block = self.blockchain.chains[-1] if self.blockchain.chains else None
        index = len(self.blockchain.chains)

        self.log("⛏️ Đang đào block ...")

        block = Block.create_block(last_block, data, index)

        with self.mining_lock:
            if not self.global_mining:
                self.log("❌ Block bị huỷ (node khác thắng trước)")
                self.reset_round_state()
                return

            self.current_proposed_block = block
            self.current_block_hash = block.hash
            self.block_votes[block.hash] = {self.node_id()}
            self.reward(len(self.pending_tx["message"]))
            print(f"Số btc hiện tại của bạn: {self.btc}")
            self.global_mining = False
            self.is_mining = False

        self.block_miner[block.hash] = self.get_self_display()

        self.log(
            f"✅ Đào xong block #{block.index} bởi {self.get_self_display()} "
            f"→ hash={block.hash[:12]}..."
        )

        proposal = {
            "type": "BLOCK_PROPOSAL",
            "block": block.to_dict(),
            "miner": self.get_self_display(),
            "block_hash": block.hash,
        }
        self.broadcast(proposal)

        if not self.peers:
            self._commit_current_block()

    # ============= Consensus: Proposal / Vote / Commit =============
    def handle_block_proposal(self, msg):
        block_dict = msg["block"]
        miner = msg["miner"]
        bh = msg["block_hash"]

        block = Block.from_dict(block_dict)
        self.block_miner[bh] = miner

        with self.mining_lock:
            self.global_mining = False
            self.is_mining = False
            self.pending_tx = None

        self.log(
            f"Nhận BLOCK_PROPOSAL: block #{block.index} do {miner} đào, "
            f"hash={bh[:12]}..., dừng đào để xác thực."
        )

        prev = getattr(block, "previous_hash", None)
        best = self.best_proposal_for_prev.get(prev)
        if best is None or block.timestamp < best[0]:
            self.best_proposal_for_prev[prev] = (block.timestamp, bh)
            is_best_ts = True
        else:
            is_best_ts = False

        pow_ok = self.validate_block_pow(block)

        accept = pow_ok and is_best_ts
        if not pow_ok:
            self.log("→ Block không đạt PoW hoặc không nối đúng chuỗi → vote NO.")
        elif not is_best_ts:
            self.log("→ Đã có block khác cùng previous_hash với timestamp nhỏ hơn → NO.")
        else:
            self.log("→ Block hợp lệ & nhanh nhất → vote YES.")

        vote_msg = {
            "type": "BLOCK_VOTE",
            "block_hash": bh,
            "from_id": self.node_id(),
            "from_name": self.node_name.get(),
            "accept": accept,
        }
        self.broadcast(vote_msg)

    def handle_block_vote(self, msg):
        bh = msg["block_hash"]
        voter_id = msg["from_id"]
        voter_name = msg.get("from_name", voter_id)
        accept = msg["accept"]

        if self.current_block_hash != bh or self.current_proposed_block is None:
            return

        block = self.current_proposed_block
        miner_name = self.block_miner.get(bh, self.get_self_display())
        short_hash = bh[:12]

        if not accept:
            self.log(
                f"{voter_name} vote NO cho block #{block.index} "
                f"(miner={miner_name}, hash={short_hash}...) → huỷ round."
            )
            self.block_has_no.add(bh)
            self.reset_round_state()
            return

        votes = self.block_votes.setdefault(bh, set())
        if voter_id not in votes:
            votes.add(voter_id)

            total_nodes = len(self.peers) + 1
            self.log(
                f"{voter_name} vote YES cho block #{block.index} "
                f"(miner={miner_name}, hash={short_hash}...). "
                f"YES hiện tại: {len(votes)}/{total_nodes}"
            )

        total_nodes = len(self.peers) + 1
        if len(votes) >= total_nodes and bh not in self.block_has_no:
            self._commit_current_block()

    def _commit_current_block(self):
        if self.current_proposed_block is None or self.current_block_hash is None:
            return

        bh = self.current_block_hash
        block = self.current_proposed_block

        if not self.validate_block_pow(block):
            self.log("Trước khi commit phát hiện block không hợp lệ, hủy.")
            self.reset_round_state()
            return

        self.blockchain.appendBlock(block)
        self.refresh_block_table()

        miner_name = self.block_miner.get(bh, self.get_self_display())
        self.status.set("Block đã được toàn mạng chấp thuận")
        self.log(
            f"✅ Block #{block.index} (miner={miner_name}, "
            f"hash={bh[:12]}...) được toàn mạng YES → commit & broadcast BLOCK_COMMIT."
        )

        commit_msg = {
            "type": "BLOCK_COMMIT",
            "block": block.to_dict(),
            "miner": miner_name,
            "block_hash": bh,
        }
        self.broadcast(commit_msg)

        self.reset_round_state()

    def handle_block_commit(self, msg):
        block_dict = msg["block"]
        miner = msg["miner"]
        bh = msg["block_hash"]

        block = Block.from_dict(block_dict)
        self.block_miner[bh] = miner

        if not self.validate_block_pow(block):
            self.log("Nhận BLOCK_COMMIT nhưng block không hợp lệ → bỏ qua.")
            return

        if self.blockchain.chains:
            last = self.blockchain.chains[-1]
            if block.previous_hash != last.hash:
                self.log("BLOCK_COMMIT: block không nối tiếp chuỗi hiện tại → bỏ qua.")
                return

            if last.hash == block.hash:
                self.log("BLOCK_COMMIT: block đã tồn tại trong chain → bỏ qua.")
                return

        self.blockchain.appendBlock(block)
        self.reset_round_state()
        self.refresh_block_table()
        self.status.set(f"Block của {miner} đã được commit.")
        self.log(
            f"✅ BLOCK_COMMIT: thêm block #{block.index} của {miner}, "
            f"hash={bh[:12]}... vào chain."
        )

    # ============= SYNC =============
    def periodic_sync_loop(self):
        while True:
            time.sleep(3)
            if not self.joined or not self.peers:
                continue
            (ip, port), name = next(iter(self.peers.items()))
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(3)
                s.connect((ip, port))
                s.send(json.dumps({"type": "SYNC_REQUEST"}).encode())
                data = s.recv(8192)
                if data:
                    msg = json.loads(data.decode())
                    self.handle_message(msg)
                s.close()
            except Exception as e:
                print(f"[SYNC] Lỗi sync với {name} @ {ip}:{port}: {e}\n")

    def refresh_block_table(self):
        """Cập nhật bảng blockchain: có thêm cột miner, data tự giãn rộng theo độ dài tx."""
        for row in self.block_tree.get_children():
            self.block_tree.delete(row)

        max_data_len = 0

        for b in self.blockchain.chains:
            miner_name = self.block_miner.get(b.hash, "")

            # cố gắng parse payload để lấy miner + tx đẹp hơn
            display_data = str(b.data)
            try:
                payload = json.loads(b.data)
                if isinstance(payload, dict):
                    miner_name = payload.get("miner", miner_name)
                    tx = payload.get("tx", None)
                    if isinstance(tx, dict):
                        # chỉ show from/to/amount cho gọn
                        frm = tx.get("from", "") or ""
                        to = tx.get("to", "") or ""
                        amt = tx.get("amount", "")
                        msg = tx.get("message", "")
                        display_data = f"{frm} -> {to} | {amt}$ | {msg}"
                    else:
                        display_data = str(tx)
            except Exception:
                pass

            max_data_len = max(max_data_len, len(display_data))

            self.block_tree.insert(
                "",
                tk.END,
                values=(
                    b.index,
                    time.strftime("%H:%M:%S", time.localtime(b.timestamp)),
                    miner_name,
                    display_data,
                    getattr(b, "previous_hash", None),
                    str(b.hash)[:20],
                ),
            )

        # điều chỉnh width cột DATA theo độ dài tx (giới hạn 600px)
        if max_data_len > 0:
            width = min(600, max_data_len * 7)  # ước lượng 7px / ký tự
            self.block_tree.column("data", width=width)


if __name__ == "__main__":
    root = tk.Tk()
    app = PeerNode(root)
    root.mainloop()
