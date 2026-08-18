
// uses RSA + AES encryption to encrypt large data
// if size of the data is less than
const MAX_BLOCK_LENGTH = 122;
const AES_KEY_LENGTH = 256;
const AES_IV_LENGTH = 256;

function dbGenerateRSAKeys() {
    return generateRSAKeyPair();
}

async function dbGenerateAESKeys() {
    var result = {
        key: '',
        iv: '',
    };

    var passphrase = generatePassphrase();
    result.key = await getKeyFromPassphrase(passphrase);
    result.iv = await getIvFromPassphrase(passphrase);

    return result;
}

async function dbEncryptByte(data, publicKey) {
    if (data.byteLength <= MAX_BLOCK_LENGTH) {
        const encData = await encryptRsa(data, publicKey);
        var result = new Uint8Array(1+encData.byteLength);
        result[0] = 48; // 48 is the ASCII code for '0'. 0 means the data is encrypted using RSA only
        result.set(new Uint8Array(encData), 1);
        return result;
    }

    var aes = await dbGenerateAESKeys();
    encData = await encryptAes(data, aes.key, aes.iv);

    bAesKey = _stringToArrayBuffer(aes.key);
    bAesIv = _stringToArrayBuffer(aes.iv);
    const encAesKey = await encryptRsa(bAesKey, publicKey);
    const encAesIv = await encryptRsa(bAesIv, publicKey);

    var result = new Uint8Array(1+encAesKey.byteLength+encAesIv.byteLength+encData.byteLength);

    result[0] = 49; // 49 is the ASCII code for '1'. 1 means the data is encrypted using RSA + AES
    result.set(new Uint8Array(encAesKey), 1);
    result.set(new Uint8Array(encAesIv), 1+encAesKey.byteLength);
    result.set(new Uint8Array(encData), 1+encAesKey.byteLength+encAesIv.byteLength);

    //alert(encAesKey.byteLength.toString());
    //alert(encAesIv.byteLength.toString());
    return result;
}

async function dbDecryptByte(encData, privateKey) {
    encData = new Uint8Array(encData);
    if (encData[0] == 48) { // 48 is the ASCII code for '0'. 0 means the data is encrypted using RSA only
        encData = new Uint8Array(encData.slice(1)); // remove the prefix
        const result = await decryptRsa(encData, privateKey);
        return result;
    }
    if (encData[0] != 49) {
        alert("Invalid prefix in encrypted data");
    }

    const encAesKey = encData.slice(1, 1 + AES_KEY_LENGTH);
    const encAesIv = encData.slice(1 + AES_KEY_LENGTH, 1 + AES_KEY_LENGTH + AES_IV_LENGTH);
    encData = encData.slice(1 + AES_KEY_LENGTH + AES_IV_LENGTH);

    const bAesKey = await decryptRsa(encAesKey, privateKey);
    const bAesIv = await decryptRsa(encAesIv, privateKey);
    const aesKey = _stringFromArrayBuffer(bAesKey);
    const aesIv = _stringFromArrayBuffer(bAesIv);
    const data = await decryptAes(encData, aesKey, aesIv);

    return data;
}

async function dbEncryptString(str, publicKey) {
    var data = _stringToArrayBuffer(str);
    var encData = await dbEncryptByte(data, publicKey);
    var result = _arrayBufferToBase64(encData);

    return result;
}

async function dbDecryptString(encStrB64, privateKey) {
    var encData = _base64StringToArrayBuffer(encStrB64);
    var data = await dbDecryptByte(encData, privateKey);
    var result = _stringFromArrayBuffer(data);

    return result;
}
