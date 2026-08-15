import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from flask import current_app

class CredentialEncryptor:
    """凭据加密器"""
    
    @staticmethod
    def get_cipher():
        """获取加密器实例"""
        secret_key = current_app.config.get('SECRET_KEY')
        if not secret_key:
            raise RuntimeError('SECRET_KEY 未配置，无法加解密设备凭据。请通过环境变量设置 SECRET_KEY。')
        
        # 使用PBKDF2派生固定长度的密钥
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b'credential_salt',  # 生产环境中应该使用随机salt并存储
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
        return Fernet(key)
    
    @staticmethod
    def encrypt(data):
        """加密数据"""
        if not data:
            return None
        cipher = CredentialEncryptor.get_cipher()
        return cipher.encrypt(data.encode()).decode()
    
    @staticmethod
    def decrypt(encrypted_data):
        """解密数据"""
        if not encrypted_data:
            return None
        try:
            cipher = CredentialEncryptor.get_cipher()
            return cipher.decrypt(encrypted_data.encode()).decode()
        except Exception as e:
            current_app.logger.error(f"解密失败: {str(e)}")
            return None
    
    @staticmethod
    def is_encrypted(data):
        """检查数据是否已加密（简单的启发式检查）"""
        if not data:
            return False
        # Fernet加密的数据有固定的格式
        try:
            cipher = CredentialEncryptor.get_cipher()
            cipher.decrypt(data.encode())
            return True
        except:
            return False