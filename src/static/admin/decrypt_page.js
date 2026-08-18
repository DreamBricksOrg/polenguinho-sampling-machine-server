// --- Auth (mesmo padrão do admin.html: JWT em localStorage) ---

const getToken = () => localStorage.getItem("adminToken") || "";

function ensureToken() {
    const token = getToken();
    if (!token) {
        window.location.href = "/templates/admin/login.html";
        return null;
    }
    return token;
}

// --- Helpers de UI ---

function setStatus(elementId, message, isError = false) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("error", isError);
    el.classList.toggle("success", !isError && Boolean(message));
}

function downloadBlob(filename, blobParts, mimeType) {
    const blob = new Blob(blobParts, { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

function readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsText(file);
    });
}

function csvEscape(value) {
    const str = String(value ?? "");
    if (/[",\n]/.test(str)) {
        return '"' + str.replace(/"/g, '""') + '"';
    }
    return str;
}

function usersToCsv(users) {
    const header = ["id", "criado_em", "nome", "email", "telefone", "retiradas"];
    const lines = [header.join(",")];
    for (const user of users) {
        lines.push(header.map((field) => csvEscape(user[field])).join(","));
    }
    return lines.join("\n");
}

// Nome do arquivo com o datetime atual em horário de Brasília (UTC-3): dd_mm_aaaa_hh_mm.
function buildCsvFilename() {
    const brt = new Date(Date.now() - 3 * 60 * 60 * 1000);
    const dd = String(brt.getUTCDate()).padStart(2, "0");
    const mm = String(brt.getUTCMonth() + 1).padStart(2, "0");
    const aaaa = brt.getUTCFullYear();
    const hh = String(brt.getUTCHours()).padStart(2, "0");
    const min = String(brt.getUTCMinutes()).padStart(2, "0");
    return `polenguinho_cadastros_${dd}_${mm}_${aaaa}_${hh}_${min}.csv`;
}

// --- Status da criptografia ---

async function loadEncryptionStatus() {
    const el = document.getElementById("encryptionStatus");
    const token = ensureToken();
    if (!token || !el) return;
    try {
        const res = await fetch("/api/admin/encryption-status", {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 401) {
            localStorage.removeItem("adminToken");
            window.location.href = "/templates/admin/login.html";
            return;
        }
        const data = await res.json();
        el.textContent = data.enabled
            ? "Criptografia: ATIVA (os cadastros novos são cifrados no navegador)."
            : "Criptografia: DESATIVADA (os cadastros são armazenados em texto puro).";
        el.classList.toggle("active", Boolean(data.enabled));
    } catch (error) {
        el.textContent = "Não foi possível consultar o status da criptografia.";
    }
}

// --- Menu ---

function showTab(tabId, buttonId) {
    for (const tab of document.querySelectorAll(".tab")) {
        tab.classList.remove("active");
    }
    for (const button of document.querySelectorAll(".menu-button")) {
        button.classList.remove("active");
    }
    document.getElementById(tabId).classList.add("active");
    document.getElementById(buttonId).classList.add("active");
}

const btnMenuKeys = document.getElementById("btnMenuKeys");
const btnMenuDecrypt = document.getElementById("btnMenuDecrypt");
if (btnMenuKeys && btnMenuDecrypt) {
    btnMenuKeys.addEventListener("click", () => showTab("tabKeys", "btnMenuKeys"));
    btnMenuDecrypt.addEventListener("click", () => showTab("tabDecrypt", "btnMenuDecrypt"));
    showTab("tabKeys", "btnMenuKeys");
}

// --- Gerar chaves ---

const btnGenerateKeys = document.getElementById("btnGenerateKeys");
if (btnGenerateKeys) {
    btnGenerateKeys.addEventListener("click", async () => {
        try {
            const keyPair = await dbGenerateRSAKeys();
            downloadBlob("public_key.pem", [keyPair.publicKey], "application/x-pem-file");
            downloadBlob("private_key.pem", [keyPair.privateKey], "application/x-pem-file");
            setStatus(
                "keysStatus",
                "Par de chaves gerado e baixado. Envie public_key.pem para " +
                    "src/static/sample/js/crypt/public_key.pem no servidor e guarde " +
                    "private_key.pem em local seguro — sem ele os dados cifrados não " +
                    "podem ser lidos."
            );
        } catch (error) {
            setStatus("keysStatus", "Erro ao gerar chaves: " + error.message, true);
        }
    });
}

// --- Descriptografar dados ---

let loadedPrivateKeyPem = null;

const privateKeyDropZone = document.getElementById("privateKeyDropZone");
const privateKeyFileInput = document.getElementById("privateKeyFile");

async function loadPrivateKeyFile(file) {
    if (!file) return;
    loadedPrivateKeyPem = await readFileAsText(file);
    setStatus("privateKeyStatus", "Arquivo carregado: " + file.name);
}

if (privateKeyDropZone) {
    privateKeyDropZone.addEventListener("click", () => privateKeyFileInput.click());

    privateKeyDropZone.addEventListener("dragover", (event) => {
        event.preventDefault();
        privateKeyDropZone.classList.add("drag-over");
    });

    privateKeyDropZone.addEventListener("dragleave", () => {
        privateKeyDropZone.classList.remove("drag-over");
    });

    privateKeyDropZone.addEventListener("drop", async (event) => {
        event.preventDefault();
        privateKeyDropZone.classList.remove("drag-over");
        await loadPrivateKeyFile(event.dataTransfer.files[0]);
    });

    privateKeyFileInput.addEventListener("change", async (event) => {
        await loadPrivateKeyFile(event.target.files[0]);
    });
}

// Tenta descriptografar; se o valor não estiver cifrado (ex.: cadastro feito
// com a criptografia desativada), devolve o próprio valor sem quebrar o CSV.
async function decryptFieldOrFallback(value) {
    if (!value) return "";
    try {
        return await dbDecryptString(value, loadedPrivateKeyPem);
    } catch (error) {
        return value;
    }
}

const btnDownloadDecryptedCsv = document.getElementById("btnDownloadDecryptedCsv");
if (btnDownloadDecryptedCsv) {
    btnDownloadDecryptedCsv.addEventListener("click", async () => {
        if (!loadedPrivateKeyPem) {
            setStatus("decryptStatus", "Carregue a chave privada antes de continuar.", true);
            return;
        }

        const token = ensureToken();
        if (!token) return;

        try {
            setStatus("decryptStatus", "Buscando cadastros...");
            const response = await fetch("/api/admin/users/raw", {
                headers: { Authorization: `Bearer ${token}` },
            });
            if (response.status === 401) {
                localStorage.removeItem("adminToken");
                window.location.href = "/templates/admin/login.html";
                return;
            }
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
            const users = await response.json();

            const decryptedUsers = [];
            for (const user of users) {
                decryptedUsers.push({
                    id: user.id,
                    criado_em: user.created_at,
                    nome: await decryptFieldOrFallback(user.name),
                    email: await decryptFieldOrFallback(user.email),
                    telefone: await decryptFieldOrFallback(user.phone),
                    retiradas: user.productsPicked ?? 0,
                });
            }

            downloadBlob(buildCsvFilename(), [usersToCsv(decryptedUsers)], "text/csv");
            setStatus("decryptStatus", "CSV descriptografado baixado.");
        } catch (error) {
            setStatus("decryptStatus", "Erro ao descriptografar cadastros: " + error.message, true);
        }
    });
}

window.addEventListener("DOMContentLoaded", () => {
    ensureToken();
    loadEncryptionStatus();
});
