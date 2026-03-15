const axios = require("axios");
const { URL } = require("url");
const dns = require("dns").promises;
const net = require("net");

// Patterns d'adresses privées/internes à bloquer (protection SSRF)
const PRIVATE_IP_PATTERNS = [
    /^localhost$/i,
    /^127\./,
    /^10\./,
    /^172\.(1[6-9]|2[0-9]|3[01])\./,
    /^192\.168\./,
    /^0\.0\.0\.0/,
    /^169\.254\./, // link-local
    /^::1$/,
    /^fc[0-9a-f]{2}:/i, // IPv6 ULA
    /^fe80:/i,           // IPv6 link-local
];

function isPrivateAddress(hostname) {
    return PRIVATE_IP_PATTERNS.some((p) => p.test(hostname));
}

function isPrivateIp(ip) {
    const ipVersion = net.isIP(ip);
    if (ipVersion === 4) {
        const octets = ip.split(".").map((v) => Number(v));
        if (octets.length !== 4 || octets.some((v) => Number.isNaN(v))) return true;
        const [a, b] = octets;
        if (a === 10 || a === 127 || a === 0) return true;
        if (a === 169 && b === 254) return true;
        if (a === 172 && b >= 16 && b <= 31) return true;
        if (a === 192 && b === 168) return true;
        if (a === 100 && b >= 64 && b <= 127) return true;
        return false;
    }

    if (ipVersion === 6) {
        const normalized = ip.toLowerCase();
        if (normalized === "::1") return true;
        if (normalized.startsWith("fe80:")) return true;
        if (normalized.startsWith("fc") || normalized.startsWith("fd")) return true;
        if (normalized.startsWith("::ffff:")) {
            const mapped = normalized.replace("::ffff:", "");
            if (net.isIP(mapped) === 4) return isPrivateIp(mapped);
        }
        return false;
    }

    return true;
}

async function ensurePublicHost(hostname) {
    if (isPrivateAddress(hostname)) {
        throw new Error("Accès aux adresses internes refusé");
    }

    if (net.isIP(hostname) && isPrivateIp(hostname)) {
        throw new Error("Accès aux IP privées refusé");
    }

    let records;
    try {
        records = await dns.lookup(hostname, { all: true, verbatim: true });
    } catch {
        throw new Error("Impossible de résoudre le domaine");
    }

    if (!records || records.length === 0) {
        throw new Error("Aucune résolution DNS disponible");
    }

    if (records.some((entry) => isPrivateIp(entry.address))) {
        throw new Error("Le domaine pointe vers une adresse privée/interne");
    }
}

async function safeHttpGet(initialUrl, { timeoutMs, maxRedirects }) {
    let currentUrl = initialUrl;

    for (let redirectCount = 0; redirectCount <= maxRedirects; redirectCount += 1) {
        const parsed = new URL(currentUrl);

        if (!["http:", "https:"].includes(parsed.protocol)) {
            throw new Error("Protocole non autorisé (HTTP/HTTPS uniquement)");
        }

        await ensurePublicHost(parsed.hostname);

        const response = await axios.get(currentUrl, {
            timeout: timeoutMs,
            maxContentLength: 500 * 1024,
            responseType: "text",
            headers: {
                "User-Agent": "Mozilla/5.0 (compatible; DiscordBot/1.0)",
                Accept: "text/html,text/plain;q=0.9",
            },
            maxRedirects: 0,
            validateStatus: (status) => status >= 200 && status < 400,
        });

        if (response.status >= 300 && response.status < 400) {
            const location = response.headers.location;
            if (!location) {
                throw new Error("Redirection invalide sans en-tête Location");
            }
            currentUrl = new URL(location, currentUrl).toString();
            continue;
        }

        return response;
    }

    throw new Error("Trop de redirections");
}

function extractTitle(html) {
    const match = html.match(/<title[^>]*>([^<]*)<\/title>/i);
    return match ? match[1].trim() : "";
}

function extractTextFromHtml(html) {
    return html
        .replace(/<script[\s\S]*?<\/script>/gi, "")
        .replace(/<style[\s\S]*?<\/style>/gi, "")
        .replace(/<nav[\s\S]*?<\/nav>/gi, "")
        .replace(/<footer[\s\S]*?<\/footer>/gi, "")
        .replace(/<header[\s\S]*?<\/header>/gi, "")
        .replace(/<!--[\s\S]*?-->/g, "")
        .replace(/<br\s*\/?>/gi, "\n")
        .replace(/<\/p>/gi, "\n")
        .replace(/<\/div>/gi, "\n")
        .replace(/<\/h[1-6]>/gi, "\n")
        .replace(/<[^>]+>/g, " ")
        .replace(/&nbsp;/g, " ")
        .replace(/&amp;/g, "&")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/[ \t]{2,}/g, " ")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
}

/**
 * Récupère une page web et extrait son texte lisible.
 * @param {string} url - URL à récupérer
 * @param {object} options
 * @param {number} options.timeoutMs - Timeout en ms (défaut 10s)
 * @param {number} options.maxChars - Taille max du texte extrait (défaut 4000)
 * @returns {{ url, title, content }}
 */
async function fetchWebPage(url, { timeoutMs = 10000, maxChars = 4000 } = {}) {
    let parsed;
    try {
        parsed = new URL(url);
    } catch {
        throw new Error("URL invalide");
    }

    const response = await safeHttpGet(url, { timeoutMs, maxRedirects: 3 });

    const contentType = response.headers["content-type"] || "";
    let text;

    if (contentType.includes("text/html")) {
        text = extractTextFromHtml(response.data);
    } else if (
        contentType.includes("text/") ||
        contentType.includes("application/json")
    ) {
        text = String(response.data);
    } else {
        throw new Error(
            `Type de contenu non supporté : ${contentType.split(";")[0].trim()}`
        );
    }

    if (text.length > maxChars) {
        text = text.slice(0, maxChars) + "\n[… contenu tronqué]";
    }

    return {
        url: response.request?.res?.responseUrl || url,
        title: extractTitle(response.data) || parsed.hostname,
        content: text,
    };
}

module.exports = { fetchWebPage };
