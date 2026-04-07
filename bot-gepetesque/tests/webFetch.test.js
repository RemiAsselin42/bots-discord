/**
 * Tests pour src/services/webFetch.js
 *
 * Stratégie de mock : Module._load intercepte axios et dns avant le require de
 * webFetch.js. Les implémentations sont mutables via les variables _*Impl
 * pour permettre un comportement différent par test.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const Module = require("node:module");
const originalLoad = Module._load;

// ─── Stubs mutables ───────────────────────────────────────────────────────────

let _axiosGetImpl = async () => {
    throw new Error("axiosMock : aucune implémentation configurée");
};
let _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];

// axios CJS : webFetch.js lit `require("axios").default ?? require("axios")`
const _axiosMock = { default: { get: (...args) => _axiosGetImpl(...args) } };
// dns : webFetch.js lit `require("dns").promises`
const _dnsMock = { lookup: (...args) => _dnsLookupImpl(...args) };

Module._load = function (request, _parent, _isMain) {
    if (request === "axios") return _axiosMock;
    if (request === "dns") return { promises: _dnsMock };
    return originalLoad.apply(this, arguments);
};

const { fetchWebPage } = require("../src/services/webFetch");

// ─── Helper ───────────────────────────────────────────────────────────────────

function makeAxiosResponse(data, contentType = "text/html", status = 200) {
    return {
        status,
        headers: { "content-type": contentType },
        data,
        request: { res: { responseUrl: "https://example.com/" } },
    };
}

// ─── SSRF ────────────────────────────────────────────────────────────────────

test("SSRF : localhost est bloqué avant toute requête réseau", async () => {
    await assert.rejects(fetchWebPage("http://localhost/"), /Accès aux adresses internes refusé/);
});

test("SSRF : IP privée littérale (192.168.x.x) est bloquée", async () => {
    await assert.rejects(
        fetchWebPage("http://192.168.1.100/"),
        /Accès aux adresses internes refusé/
    );
});

test("SSRF : domaine dont le DNS résout vers une IP privée est bloqué", async () => {
    _dnsLookupImpl = async () => [{ address: "10.0.0.1", family: 4 }];
    await assert.rejects(
        fetchWebPage("http://evil-proxy.example.com/"),
        /Le domaine pointe vers une adresse privée\/interne/
    );
});

// ─── Happy path ───────────────────────────────────────────────────────────────

test("HTML : titre extrait et balises supprimées", async () => {
    _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];
    _axiosGetImpl = async () =>
        makeAxiosResponse(
            "<html><head><title>Ma Page</title></head><body><script>evil()</script><p>Bonjour monde</p></body></html>"
        );

    const result = await fetchWebPage("https://example.com/");
    assert.equal(result.title, "Ma Page");
    assert.ok(result.content.includes("Bonjour monde"), `contenu: ${result.content}`);
    assert.ok(!result.content.includes("<p>"), "Les balises HTML doivent être supprimées");
    assert.ok(!result.content.includes("evil()"), "Le contenu <script> doit être supprimé");
});

test("JSON / texte brut : contenu retourné sans transformation HTML", async () => {
    _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];
    _axiosGetImpl = async () => makeAxiosResponse('{"clé":"valeur"}', "application/json");

    const result = await fetchWebPage("https://api.example.com/data");
    assert.ok(result.content.includes('"clé"'), `contenu: ${result.content}`);
});

// ─── Rejet ────────────────────────────────────────────────────────────────────

test("Type MIME non supporté (image/png) → rejet explicite", async () => {
    _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];
    _axiosGetImpl = async () => makeAxiosResponse(Buffer.alloc(10), "image/png");

    await assert.rejects(
        fetchWebPage("https://example.com/img.png"),
        /Type de contenu non supporté/
    );
});

// ─── Troncature ───────────────────────────────────────────────────────────────

test("Contenu dépassant maxChars est tronqué avec indicateur", async () => {
    _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];
    _axiosGetImpl = async () => makeAxiosResponse(`<p>${"A".repeat(500)}</p>`);

    const result = await fetchWebPage("https://example.com/long", { maxChars: 100 });
    assert.ok(result.content.endsWith("[… contenu tronqué]"), `fin: ${result.content.slice(-30)}`);
    assert.ok(result.content.length <= 100 + "[… contenu tronqué]".length + 5);
});

// ─── Redirection ─────────────────────────────────────────────────────────────

test("Redirection 301 → 200 est suivie automatiquement", async () => {
    _dnsLookupImpl = async () => [{ address: "93.184.216.34", family: 4 }];
    let callCount = 0;
    _axiosGetImpl = async () => {
        callCount += 1;
        if (callCount === 1) {
            return {
                status: 301,
                headers: { location: "https://example.com/final", "content-type": "" },
                data: "",
                request: { res: { responseUrl: "https://example.com/" } },
            };
        }
        return makeAxiosResponse("<p>Page finale</p>");
    };

    const result = await fetchWebPage("https://example.com/redirect");
    assert.ok(result.content.includes("Page finale"), `contenu: ${result.content}`);
    assert.equal(callCount, 2, "Deux appels axios attendus (initial + redirect)");
});
