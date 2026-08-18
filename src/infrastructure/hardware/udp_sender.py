import socket
import threading
from shared.singleton import Singleton
import structlog

log = structlog.get_logger(__name__)
import time


class UDPSender(metaclass=Singleton):
    def __init__(self, ip="127.0.0.1", port=5053):
        self.semaphore = threading.Semaphore()
        self.ip = ip
        self.port = port
        self.lock = threading.Lock()
        self.max_retries = 3
        self.retry_delay = 1
        self._initialize_socket()

    def _initialize_socket(self):
        """Inicializa o socket UDP."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Define um timeout para operações de socket
            self.sock.settimeout(5)
            log.info("udp-socket-initialized", ip=self.ip, port=self.port)
        except Exception as e:
            log.error("udp-socket-init-failed",
                     error=str(e), ip=self.ip, port=self.port)
            self.sock = None
    
    def _is_socket_valid(self):
        """Verifica se o socket está válido."""
        return self.sock is not None
    
    def _reconnect_if_needed(self):
        """Reconecta o socket se necessário."""
        if not self._is_socket_valid():
            log.warning("udp-socket-reconnecting",
                       ip=self.ip, port=self.port)
            self._initialize_socket()
    
    def send(self, msg, retry_count=0):
        """
        Envia mensagem UDP com retry automático e tratamento de erro.
        
        Args:
            msg: Mensagem a ser enviada
            retry_count: Contador interno de tentativas
        """
        if retry_count >= self.max_retries:
            log.error("udp-max-retries-exceeded",
                     message=msg, ip=self.ip, port=self.port)
            return False
        
        try:
            with self.lock:
                self._reconnect_if_needed()
                
                if not self._is_socket_valid():
                    log.error("udp-socket-invalid",
                             message=msg, ip=self.ip, port=self.port)
                    return False
                
                # Envia a mensagem
                encoded_msg = str.encode(msg)
                bytes_sent = self.sock.sendto(encoded_msg, (self.ip, self.port))
                
                if bytes_sent == len(encoded_msg):
                    log.info("udp-message-sent",
                            message=msg, bytes_sent=bytes_sent,
                            ip=self.ip, port=self.port)
                    return True
                else:
                    log.warning("udp-partial-send",
                               message=msg, bytes_sent=bytes_sent,
                               expected=len(encoded_msg))
                    return False
                    
        except socket.timeout:
            log.warning("udp-send-timeout",
                       message=msg, retry_count=retry_count,
                       ip=self.ip, port=self.port)
            time.sleep(self.retry_delay)
            return self.send(msg, retry_count + 1)
            
        except socket.error as e:
            log.error("udp-socket-error",
                     error=str(e), message=msg, retry_count=retry_count,
                     ip=self.ip, port=self.port)
            # Tenta reconectar
            self._initialize_socket()
            time.sleep(self.retry_delay)
            return self.send(msg, retry_count + 1)
            
        except Exception as e:
            log.error("udp-unexpected-error",
                     error=str(e), message=msg, retry_count=retry_count,
                     ip=self.ip, port=self.port)
            return False
    
    def send_with_confirmation(self, msg, max_attempts=3):
        """
        Envia mensagem UDP com múltiplas tentativas para garantir entrega.
        
        Args:
            msg: Mensagem a ser enviada
            max_attempts: Número máximo de tentativas
            
        Returns:
            bool: True se enviado com sucesso, False caso contrário
        """
        for attempt in range(max_attempts):
            if self.send(msg):
                return True
            
            if attempt < max_attempts - 1:
                log.info("udp-retry-attempt",
                    message=msg, attempt=attempt + 1,
                    max_attempts=max_attempts)
                time.sleep(self.retry_delay * (attempt + 1))
        
        log.error("udp-all-attempts-failed",
                 message=msg, max_attempts=max_attempts,
                 ip=self.ip, port=self.port)
        return False
    
    def close(self):
        """Fecha o socket UDP."""
        try:
            if self.sock:
                self.sock.close()
                self.sock = None
                log.info("udp-socket-closed", ip=self.ip, port=self.port)
        except Exception as e:
            log.error("udp-socket-close-error", error=str(e))
    
    def __del__(self):
        """Destrutor para garantir que o socket seja fechado."""
        self.close()
