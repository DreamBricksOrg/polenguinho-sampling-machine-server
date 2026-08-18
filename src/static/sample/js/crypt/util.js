const uint8ArrayfromHexString = (hexString) => Uint8Array.from(hexString.match(/.{1,2}/g).map((byte) => parseInt(byte, 16)));

function _base64StringToArrayBuffer(b64str) {
    const byteStr = atob(b64str);
    const bytes = new Uint8Array(byteStr.length);
    for (let i = 0; i < byteStr.length; i++) {
        bytes[i] = byteStr.charCodeAt(i);
    }
    return bytes.buffer;
}

function _arrayBufferToBase64(arrayBuffer) {
    const byteArray = new Uint8Array(arrayBuffer);
    let byteString = '';
    for (let i = 0; i < byteArray.byteLength; i++) {
        byteString += String.fromCharCode(byteArray[i]);
    }
    const b64 = window.btoa(byteString);
    return b64;
}

const _arrayBufferFromHexString = (hexString) => {
    const bytes = Uint8Array.from(hexString.match(/.{1,2}/g).map((byte) => parseInt(byte, 16)));
    return bytes.buffer;
};

const _stringToArrayBuffer = (str) => {
    const encoder = new TextEncoder();
    return encoder.encode(str).buffer;
};

const _stringFromArrayBuffer = (buffer) => {
    const decoder = new TextDecoder();
    return decoder.decode(buffer);
};

const _arrayBufferToHexString = (buffer) => {
    const byteArray = new Uint8Array(buffer);
    const hexCodes = [...byteArray].map(value => {
        const hexCode = value.toString(16);
        const paddedHexCode = hexCode.padStart(2, '0');
        return paddedHexCode;
    });
    return hexCodes.join('');
};

/**
 * sends a request to the specified url from a form. this will change the window location.
 * @param {string} path the path to send the post request to
 * @param {object} params the parameters to add to the url
 * @param {string} [method=post] the method to use on the form
 */

function post(path, params, method='post') {

  // The rest of this code assumes you are not using a library.
  // It can be made less verbose if you use one.
  const form = document.createElement('form');
  form.method = method;
  form.action = path;

  for (const key in params) {
    if (params.hasOwnProperty(key)) {
      const hiddenField = document.createElement('input');
      hiddenField.type = 'hidden';
      hiddenField.name = key;
      hiddenField.value = params[key];

      form.appendChild(hiddenField);
    }
  }

  document.body.appendChild(form);
  form.submit();
}

function getNameInitials(name) {
    const names = name.split(" ");
    var result = names[0] + ' ';

    for (let i = 1; i < names.length; i++) {
        result += names[i].charAt(0).toUpperCase() + '.';
        if (i < names.length-1) {
            result += ' ';
        }
    }
    return result;
}

function sanitize(value) {
    return value.replaceAll(',', '.');
}

function maskDocument(value) {
    return value.substr(0, 2) + "*.***.**" + value.substr(-4);
}

function createLinkAndClickIt(url) {
    var link = document.createElement("a");
    link.id = 'my_auto_link'; //give it an ID!
    link.href=url;
    link.click();
}
