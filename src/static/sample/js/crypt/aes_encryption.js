
const _digestMessage = async (message) => {
    const data = _stringToArrayBuffer(message);
    const hash = await crypto.subtle.digest("SHA-256", data);
    return hash;
};

const generatePassphrase = () => {
    var result = "";
    var hex64 = "0123456789ABCDEFGHIJKLMNOPQESTUVWXYZabcdefghijklmnopqestuvwxyz@_"

    for (i = 0; i < 64; i++) {
        result += hex64.charAt(Math.floor(Math.random() * 64));
        //result += String.fromCharCode((Math.floor(Math.random() * 64))+48);
        //Initially this was charAt(chance.integer({min: 0, max: 15}));
    }
    return result;
}

const getKeyFromPassphrase = async (passphrase) => {
    const key = await _digestMessage(passphrase);
    const keyHex = _arrayBufferToHexString(key);
    return keyHex;
};

const getIvFromPassphrase = async (passphrase) => {
    const keyHex = await getKeyFromPassphrase(passphrase);
    const ivHex = keyHex.substring(0, 32);
    return ivHex;
};

const encryptAes = async (fileArrayBuffer, keyHex, ivHex) => {
    // decode the Hex-encoded key and IV
    const ivArrayBuffer = _arrayBufferFromHexString(ivHex);
    const keyArrayBuffer = _arrayBufferFromHexString(keyHex);
    // prepare the secret key for encryption
    const secretKey = await crypto.subtle.importKey('raw', keyArrayBuffer, {
        name: 'AES-CBC',
        length: 256
    }, true, ['encrypt', 'decrypt']);
    // encrypt the text with the secret key
    const ciphertextArrayBuffer = await crypto.subtle.encrypt({
        name: 'AES-CBC',
        iv: ivArrayBuffer
    }, secretKey, fileArrayBuffer);
    return ciphertextArrayBuffer;
};

// openssl enc -aes-256-cbc -nosalt -d -in test_car_encrypted_web.jpg -out test_car_enc_web_dec_openssl.jpg -K <key in Hex> -iv <iv in Hex>
const decryptAes = async (fileArrayBuffer, keyHex, ivHex) => {
    // decode the Hex-encoded key and IV
    const ivArrayBuffer = _arrayBufferFromHexString(ivHex);
    const keyArrayBuffer = _arrayBufferFromHexString(keyHex);
    // prepare the secret key for encryption
    const secretKey = await crypto.subtle.importKey('raw', keyArrayBuffer, {
        name: 'AES-CBC',
        length: 256
    }, true, ['encrypt', 'decrypt']);
    // decrypt the ciphertext with the secret key
    const decryptedBuffer = await crypto.subtle.decrypt({
        name: 'AES-CBC',
        iv: ivArrayBuffer
    }, secretKey, fileArrayBuffer);
    // return the decrypted data as an ArrayBuffer
    return decryptedBuffer;
};
