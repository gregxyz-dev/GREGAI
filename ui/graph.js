/**
 * graph.js
 *
 * Graf siłowy węzłów wiedzy GREGAI - prawdziwa przestrzeń 3D (Three.js,
 * ui/vendor/three.min.js + OrbitControls.js, wendorowane lokalnie: GREGAI
 * ma działać offline, bez CDN). Poprzednia wersja rysowała płaski canvas 2D
 * z iluzją głębi (gradient na "kulkach"); to jest prawdziwa bryła z
 * prawdziwym oświetleniem - prośba Grzegorza po zobaczeniu szkicu.
 *
 * Publiczny kontrakt tej klasy (konstruktor, loadData, focusNode,
 * activeTypes, setTypeActive) i funkcja startRenderLoop są CELOWO
 * identyczne jak w wersji 2D - ui/app.js nie wie i nie musi wiedzieć, że
 * silnik pod spodem się zmienił.
 *
 * Świadome uproszczenie względem 2D: nie da się już ręcznie przeciągać
 * pojedynczego węzła (lewy przycisk + przeciąganie steruje teraz kamerą -
 * OrbitControls). W zamian pozycja/kąt kamery zapamiętują się per
 * przeglądarka (localStorage), tak jak wcześniej zapamiętywał się ręczny
 * układ węzłów - ten sam zamysł, przeniesiony na nowy sposób patrzenia.
 */

const TYPE_COLORS = {
  Call: "--type-call",
  Note: "--type-note",
  Concept: "--type-concept",
  Project: "--type-project",
  Person: "--type-person",
  Client: "--type-client",
  Invoice: "--type-invoice",
  Proposal: "--type-proposal",
  Sop: "--type-sop",
  Brief: "--type-brief",
  Campaign: "--type-campaign",
  Routine: "--type-routine",
  Wiki: "--type-wiki",
  Journal: "--type-journal",
  Wiedza: "--type-wiedza",
  Nauka: "--type-nauka",
  Memory: "--type-memory",
};

const IDLE_PULSE_INTERVAL_MS = 30000; // ozdoba: raz na pół minuty, nie częściej
const IDLE_PULSE_MAX_NODES = 400;
const LABEL_MAX_CHARS = 40;
const HOVER_DIM_OPACITY = 0.1;

// Fizyka w 3D - te same stałe i ten sam pomysł (siatka przestrzenna zamiast
// O(n²) par), tylko komórka ma teraz trzy współrzędne zamiast dwóch.
const REPULSION_CELL_SIZE = 46;
const REPULSION_MAX_DIST = 60;
const SETTLED_ENERGY_PER_NODE = 0.01;
const MAX_ACTIVE_FRAMES = 600;
function maxActiveFrames(n) {
  return n > 600 ? Math.max(90, Math.round((MAX_ACTIVE_FRAMES * 600) / n)) : MAX_ACTIVE_FRAMES;
}
const MAX_VELOCITY = 12;
const COORD_LIMIT = 20000;
const EDGE_TARGET_LEN = 34;

const CAMERA_MIN_DIST = 24;
const CAMERA_MAX_DIST = 1400;
const DRAG_THRESHOLD_PX = 3;
const SELECT_POP_MS = 420;

// Węzeł "zasypia" do bezruchu po tylu ms braku interakcji z kamerą - wtedy
// pętla rysowania przestaje się wznawiać (patrz startRenderLoop), dokładnie
// ta sama zasada "śpij, gdy nic się nie dzieje" co w wersji 2D i w szkicu
// artefaktu, którego Grzegorz już widział i zaakceptował.
const CAMERA_WAKE_MS = 2500;
const ORBIT_FRAME_MS = 33; // 1.18.0: krążenie kamery ~30 klatek/s (patrz render)
// 1.32.2 (audyt tura 7, energooszczędność): krążenie gaśnie po 90 s bez ruchu myszą/palcem
// albo przewijania - otwarte w tle Węzły nie liczą klatek bez końca. Ruch je wznawia.
// 1.32.10 (audyt tura 14, pomiar): 20 s zamiast 90 s - krążenie to ozdoba, a w Węzłach
// otwartych w tle liczyło klatki przez półtorej minuty.
const ORBIT_IDLE_MS = 20000;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

class Graph {
  constructor(canvas, { onSelect, canSelect, onTypesChanged, onInfo } = {}) {
    this.canvas = canvas;
    this.onSelect = onSelect || (() => {});
    this.canSelect = canSelect || (() => true);
    this.onTypesChanged = onTypesChanged || (() => {});
    this.onInfo = onInfo || (() => {});

    this.nodes = [];
    this.edges = [];
    this.byId = new Map();
    this.activeTypes = new Set();
    this.hoveredNode = null;
    this.selectedNode = null;
    this.activePath = new Set();
    // Węzeł na KOŃCU trasy (ten, który został shift-kliknięty jako cel -
    // patrz _tracePath) - zgłoszenie Grzegorza 2026-10-19: w trybie
    // śledzenia trasy ma podświetlać się też TO, co jest połączone z tym
    // krańcem, jako podgląd możliwego następnego kroku, zanim się tam
    // kliknie. Patrz _refreshFocus niżej.
    this._pathFrontier = null;

    this.pulseEdge = null;
    this.pulseProgress = 0;
    this._selectAnim = null;

    this._settled = false;
    this._activeFrames = 0;
    this._dirty = true;
    this._colors = new Map();
    this._materials = new Map();   // typ -> MeshStandardMaterial (dzielony, jeden na typ)
    this._haloMaterials = new Map(); // typ -> MeshBasicMaterial (poświata hubów)
    this._focus = false;
    this._focusSet = null;
    this._wakeUntil = 0;
    this._labelEl = new Map(); // node -> element etykiety w warstwie DOM

    this._failed = false; // true, gdy WebGL się nie uruchomił - metody publiczne wtedy nic nie robią

    try {
      this._initThree();
    } catch (err) {
      this._failed = true;
      console.error("GREGAI: nie udało się uruchomić widoku 3D węzłów.", err);
      this.onInfo("Nie udało się uruchomić widoku 3D (WebGL). Reszta aplikacji działa normalnie.");
      return;
    }
    this._bindEvents();
  }

  // --- Inicjalizacja sceny ---
  _initThree() {
    this.scene = new THREE.Scene();
    // 1.31.0: osobny token tła mapy (kadr.css: ciepły brąz), z zapasem na --bg.
    this.scene.background = new THREE.Color(this._cv("--graph-bg") || this._cv("--bg") || "#07070a");
    this.scene.fog = new THREE.FogExp2(this.scene.background.getHex(), 0.0019);

    this.camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 1, 6000);
    this.camera.position.set(60, 90, 420);

    // failIfMajorPerformanceCaveat:false - bez tego WebGL bywa odrzucany, gdy
    // przeglądarka ma tylko programowe (nie sprzętowe) renderowanie; patrz
    // notatka w historii tej wersji (ten sam błąd wystąpił w podglądzie
    // artefaktu-szkicu, zanim trafił tu do produktu).
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      failIfMajorPerformanceCaveat: false,
      powerPreference: "default",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);

    this.scene.add(new THREE.AmbientLight(0x3a3a42, 1.15));
    const key = new THREE.DirectionalLight(0xfff2e6, 1.1);
    key.position.set(-140, 180, 200);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x6a7bff, 0.3);
    rim.position.set(140, -70, -160);
    this.scene.add(rim);

    // Siatka pod węzłami - ten sam pomysł "stania na czymś", co płaska
    // siatka CSS pod kanwą w wersji 2D, tylko teraz naprawdę w przestrzeni.
    this._grid = new THREE.GridHelper(900, 36, 0x4a2c18, 0x2e1b0e); // 1.31.0: siatka w ciepłym brązie (kadr)
    this._grid.position.y = -180;
    this.scene.add(this._grid);

    // Skybox: wielka, prawie niewidoczna siatkowa kula otaczająca cały graf -
    // prośba Grzegorza po zobaczeniu 1.7.0, żeby przestrzeń wokół węzłów była
    // lepiej "czytelna". To JEDNA geometria zbudowana raz (nie per klatka) i
    // bez żadnej animacji/obrotu - gdyby się kręciła, scena byłaby "brudna"
    // (dirty) w każdej klatce na zawsze i pętla rysowania nigdy by nie
    // usypiała (patrz startRenderLoop), co kłóciłoby się z ograniczeniem
    // procesora tego laptopa. Dwie powłoki (większa chłodna fioletowa,
    // mniejsza cieplejsza różowa) dają wrażenie głębi bez dodatkowego kosztu
    // w czasie - to tylko dwie dodatkowe, statyczne siatki linii. `fog =
    // false`, bo inaczej gęsta mgła (FogExp2, patrz niżej) na takim
    // dystansie gasi je niemal całkowicie - zanikanie odległości ma działać
    // na węzłach/krawędziach, nie na samym "niebie" wokół nich.
    const skyOuter = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.SphereGeometry(1300, 20, 14)),
      new THREE.LineBasicMaterial({ color: this._cv("--purple") || "#8b5cf6", transparent: true, opacity: 0.07, depthWrite: false, fog: false })
    );
    this.scene.add(skyOuter);
    const skyInner = new THREE.LineSegments(
      new THREE.WireframeGeometry(new THREE.SphereGeometry(760, 14, 10)),
      new THREE.LineBasicMaterial({ color: this._cv("--pink") || "#ff4d6d", transparent: true, opacity: 0.05, depthWrite: false, fog: false })
    );
    this.scene.add(skyInner);

    this._sphereGeo = new THREE.SphereGeometry(1, 20, 14);

    this._lineGroup = new THREE.Group();
    this.scene.add(this._lineGroup);

    this._controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this._controls.enableDamping = true;
    this._controls.dampingFactor = 0.08;
    this._controls.minDistance = CAMERA_MIN_DIST;
    this._controls.maxDistance = CAMERA_MAX_DIST;
    this._controls.addEventListener("change", () => this._wakeCamera());
    this._controls.addEventListener("end", () => this._saveCamera());
    // 1.17.10 (prośba Grzegorza, 2026-10-21): kamera leciutko krąży wokół grafu,
    // gdy nikt go nie dotyka (OrbitControls.autoRotate: krąży tylko w stanie
    // bezczynności - przeciągnięcie myszą przerywa, puszczenie wznawia).
    // -0.5 (1.17.11, prośba Grzegorza: "w prawą stronę i odrobinę szybciej")
    // = jeden obrót w ok. 60 s przy 60 fps, ujemna wartość odwraca kierunek
    // względem domyślnego OrbitControls; ruch "żyje", nie kręci w głowie. Wyłączone przy prefers-reduced-motion i gdy segment Węzłów jest
    // schowany (setAutoOrbit z app.js) - inaczej karta graficzna liczyłaby
    // klatki pod niewidocznym płótnem.
    // 1.18.0: krążenie jest teraz ŻĄDANIEM (setAutoOrbit z app.js) połączonym
    // w render() z dwoma warunkami: brak zaznaczonego węzła (czytasz inspektor -
    // zaznaczony węzeł nie ma odpływać z kadru) i brak "ogranicz ruch" w systemie
    // (śledzone na żywo, nie tylko przy starcie strony).
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    this._autoOrbitWanted = !reduceMotion.matches;
    const onMotionPref = (e) => { this._autoOrbitWanted = !e.matches; this._invalidate(); };
    if (reduceMotion.addEventListener) reduceMotion.addEventListener("change", onMotionPref);
    this._orbitRequested = false;
    this._orbitActive = false;
    this._lastOrbitFrame = 0;
    this._lastInput = performance.now();
    this._controls.autoRotate = false;
    this._controls.autoRotateSpeed = -0.5;

    this._raycaster = new THREE.Raycaster();

    this._labelLayer = document.getElementById("graph-labels");

    // Jedna, wspólna "aureola" na zaznaczony węzeł i druga na najechany -
    // przesuwane/skalowane do właściwego węzła, zamiast osobnego materiału
    // na każdym z, czasem kilkuset, węzłów.
    const auraGeo = this._sphereGeo;
    this._auraSelected = new THREE.Mesh(auraGeo, new THREE.MeshBasicMaterial({
      color: this._cv("--text-primary") || "#ffffff", transparent: true, opacity: 0.16, depthWrite: false,
    }));
    this._auraSelected.visible = false;
    this.scene.add(this._auraSelected);

    this._auraHover = new THREE.Mesh(auraGeo, new THREE.MeshBasicMaterial({
      color: this._cv("--text-primary") || "#ffffff", transparent: true, opacity: 0.1, depthWrite: false,
    }));
    this._auraHover.visible = false;
    this.scene.add(this._auraHover);

    // Puls skończony (420ms) przy zaznaczeniu - rozszerzająca się, gasnąca
    // powłoka wokół węzła. Jeden obiekt, odtwarzany od zera przy każdym
    // zaznaczeniu (patrz _triggerSelectPop).
    this._popMesh = new THREE.Mesh(auraGeo, new THREE.MeshBasicMaterial({
      color: this._cv("--text-primary") || "#ffffff", transparent: true, opacity: 0, depthWrite: false,
    }));
    this._popMesh.visible = false;
    this.scene.add(this._popMesh);

    // Iskra płynąca krawędzią w bezczynności (patrz _updateIdlePulse) -
    // jeden obiekt, rzadko widoczny (raz na 30s, ok. 50 klatek).
    this._pulseMesh = new THREE.Mesh(new THREE.SphereGeometry(1.6, 10, 8), new THREE.MeshBasicMaterial({
      color: this._cv("--accent") || "#ff4d6d",
    }));
    this._pulseMesh.visible = false;
    this.scene.add(this._pulseMesh);

    this._loadCamera();

    window.addEventListener("resize", () => this._resize());
  }

  _resize() {
    if (this._failed) return;
    this.camera.aspect = window.innerWidth / window.innerHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(window.innerWidth, window.innerHeight, false);
    this._invalidate();
  }

  _invalidate() {
    this._dirty = true;
    if (this._requestFrame) this._requestFrame();
  }

  _wakeCamera() {
    this._wakeUntil = performance.now() + CAMERA_WAKE_MS;
    // Obrót z krążenia (render, gałąź "tylko kamera") też wysyła "change" -
    // nie może przez to robić z każdej klatki pełnego przeliczenia sceny.
    if (this._orbitUpdating) return;
    this._invalidate();
  }

  setAutoOrbit(on) {
    // app.js: tylko gdy segment Węzłów jest widoczny i karta nie jest schowana.
    this._orbitRequested = !!on;
    if (on) this._lastInput = performance.now();  // wejście do Węzłów liczy się jak ruch
    this._invalidate();
  }

  _cv(name) {
    let value = this._colors.get(name);
    if (value === undefined) {
      value = cssVar(name);
      if (value) this._colors.set(name, value);
    }
    return value;
  }

  _materialFor(type) {
    let mat = this._materials.get(type);
    if (!mat) {
      const color = this._cv(Object.hasOwn(TYPE_COLORS, type) ? TYPE_COLORS[type] : "--type-note");
      mat = new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.12 });
      this._materials.set(type, mat);
    }
    return mat;
  }

  _haloMaterialFor(type) {
    let mat = this._haloMaterials.get(type);
    if (!mat) {
      const color = this._cv(Object.hasOwn(TYPE_COLORS, type) ? TYPE_COLORS[type] : "--type-note");
      mat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.22, depthWrite: false });
      this._haloMaterials.set(type, mat);
    }
    return mat;
  }

  // --- Kamera: ta sama idea co localStorage z pozycjami węzłów w 2D, tylko
  // teraz zapamiętuje się ramka kamery (jedyne, co teraz jest "ręcznie
  // ułożone" przez Grzegorza) - wyłącznie w tej przeglądarce. ---
  _loadCamera() {
    try {
      const raw = localStorage.getItem("gregai_graph_camera_3d");
      if (!raw) return false;
      const c = JSON.parse(raw);
      if (!c || !Array.isArray(c.pos) || !Array.isArray(c.target)) return false;
      this.camera.position.set(c.pos[0], c.pos[1], c.pos[2]);
      this._controls.target.set(c.target[0], c.target[1], c.target[2]);
      this._controls.update();
      return true;
    } catch (e) {
      return false;
    }
  }

  _saveCamera() {
    if (this._failed) return;
    try {
      const p = this.camera.position, t = this._controls.target;
      localStorage.setItem("gregai_graph_camera_3d", JSON.stringify({
        pos: [p.x, p.y, p.z], target: [t.x, t.y, t.z],
      }));
    } catch (e) { /* prywatne okno / zablokowany storage - po prostu się nie zapamięta */ }
  }

  /**
   * Wczytuje dane. keep=true (odświeżenie po zapisie/utworzeniu/usunięciu
   * notatki): zostają pozycje węzłów, zaznaczenie i wyłączone filtry typów;
   * nowe węzły lądują obok powiązanego sąsiada. Bez keep: układ od zera,
   * kamera zostaje tam, gdzie ją zapamiętano (albo w domyślnym kadrze).
   */
  // 1.29.0 (kontrola): mapa schowana (otwarta Rozmowa/Nadzorca) nie buduje siatek ani
  // nie liczy fizyki - na telefonie 2000 notatek blokowało stronę ok. 2 s przy starcie
  // i przy każdym odświeżeniu. Dane czekają i wchodzą przy pierwszym pokazaniu mapy.
  _hidden() {
    return !this.canvas || this.canvas.getClientRects().length === 0;
  }

  loadDataWhenVisible(nodes, edges, opts = {}) {
    if (this._hidden()) {
      this._deferred = [nodes, edges, opts];
      return;
    }
    this._deferred = null;
    this._everLoaded = true;
    this.loadData(nodes, edges, opts);
    try { this.onTypesChanged(); } catch (err) { /* jw. */ }
  }

  _flushDeferred() {
    if (!this._deferred) return;
    const [n, e, o] = this._deferred;
    this._deferred = null;
    this.loadData(n, e, o);
    try { this.onTypesChanged(); } catch (err) { /* lista rodzajów odświeży się przy następnej zmianie */ }
  }

  loadData(nodes, edges, { keep = false } = {}) {
    if (this._failed) return;
    const prev = keep ? new Map(this.nodes.map((n) => [n.id, n])) : new Map();
    const prevTypes = new Set(keep ? this.nodes.map((n) => n.type) : []);
    const prevActive = new Set(this.activeTypes);
    const selectedId = keep && this.selectedNode ? this.selectedNode.id : null;
    const hadCamera = keep ? true : this._loadedCameraOnce;
    this._loadedCameraOnce = true;

    // Stare siatki/halo/edge-Line trzeba usunąć ze sceny przed zbudowaniem nowych.
    // 1.27.0 (audyt): materiały-klony węzłów i geometrie/materiały krawędzi zwalniane
    // (30 odświeżeń 400 węzłów: 804 -> 24 805 geometrii w pamięci karty graficznej).
    for (const n of this.nodes) {
      if (n._mesh) { this.scene.remove(n._mesh); if (n._mesh.material) n._mesh.material.dispose(); }
      if (n._halo) this.scene.remove(n._halo);
    }
    for (const line of this._lineGroup.children.slice()) {
      this._lineGroup.remove(line);
      if (line.geometry) line.geometry.dispose();
      if (line.material) line.material.dispose();
    }
    for (const el of this._labelEl.values()) el.remove();
    this._labelEl.clear();

    this.byId.clear();
    this.nodes = nodes.map((n) => {
      const old = prev.get(n.id);
      const node = {
        ...n,
        x: old ? old.x : NaN, y: old ? old.y : NaN, z: old ? old.z : NaN,
        vx: 0, vy: 0, vz: 0,
      };
      this.byId.set(n.id, node);
      return node;
    });
    this.edges = edges
      .map((e) => ({ source: this.byId.get(e.source), target: this.byId.get(e.target) }))
      .filter((e) => e.source && e.target);

    this._placeNewNodes();
    this.activeTypes = keep
      ? new Set(this.nodes.map((n) => n.type).filter((t) => prevActive.has(t) || !prevTypes.has(t)))
      : new Set(this.nodes.map((n) => n.type));
    this._computeDegrees();

    for (const n of this.nodes) this._buildMeshFor(n);
    for (const e of this.edges) this._buildLineFor(e);

    const settleN = Math.max(1, this.nodes.length);
    this._settle(keep ? Math.min(40, Math.max(10, Math.floor(8000 / settleN))) : Math.max(settleN > 2000 ? 5 : 20, Math.min(220, Math.floor(20000 / settleN))));
    this._syncMeshPositions();
    this._wake();

    this.hoveredNode = null;
    this.selectedNode = selectedId ? (this.byId.get(selectedId) || null) : null;
    if (selectedId && !this.selectedNode && this.canSelect(null)) this.onSelect(null);
    this.activePath.clear();
    this._pathFrontier = null;
    this.pulseEdge = null;
    this._focus = false;

    this._applyVisibility();
    if (!keep && !hadCamera) this._fit();
    this._invalidate();
  }

  _buildMeshFor(node) {
    // .clone() jest tu kluczowe: _materialFor(type) cache'uje JEDEN obiekt
    // materiału na CAŁY typ (żeby nie liczyć koloru z CSS za każdym razem),
    // ale _applyVisibility() ustawia .opacity osobno DLA KAŻDEGO WĘZŁA w
    // pętli po this.nodes - gdyby wiele węzłów tego samego typu dzieliło
    // dosłownie ten sam obiekt materiału (bez klonowania), finalna
    // przezroczystość całego typu byłaby tą, którą ustawił OSTATNI
    // przetworzony węzeł tego typu, nie każdy z osobna. Zgłoszenie
    // Grzegorza (2026-10-19): zaznaczony węzeł ("Fizyka") wychodził
    // przyciemniony razem z resztą, bo późniejszy, nieprzyciemniony węzeł
    // tego samego typu nadpisywał wspólny materiał - potwierdzone testem
    // logiki poza Three.js. Klon ma ten sam kolor/recepturę co szablon
    // typu, ale własną, niezależną przezroczystość.
    const mesh = new THREE.Mesh(this._sphereGeo, this._materialFor(node.type).clone());
    mesh.userData.node = node;
    this.scene.add(mesh);
    node._mesh = mesh;
    node._halo = null; // dobudowywana leniwie w _computeDegrees-po-stronie _refreshHalos
  }

  _buildLineFor(edge) {
    const geo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    const mat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.12 });
    const line = new THREE.Line(geo, mat);
    this._lineGroup.add(line);
    edge._line = line;
  }

  // Węzły bez pozycji (nowe): obok średniej pozycji powiązanych sąsiadów w 3D,
  // a bez sąsiadów losowo w chmurze wokół środka.
  _placeNewNodes() {
    const neighbours = new Map();
    for (const e of this.edges) {
      if (!neighbours.has(e.source)) neighbours.set(e.source, []);
      if (!neighbours.has(e.target)) neighbours.set(e.target, []);
      neighbours.get(e.source).push(e.target);
      neighbours.get(e.target).push(e.source);
    }
    const jitter = (r) => (Math.random() - 0.5) * r;
    for (const node of this.nodes) {
      if (Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z)) continue;
      const placed = (neighbours.get(node) || []).filter((o) => Number.isFinite(o.x));
      if (placed.length) {
        node.x = placed.reduce((a, o) => a + o.x, 0) / placed.length + jitter(26);
        node.y = placed.reduce((a, o) => a + o.y, 0) / placed.length + jitter(26);
        node.z = placed.reduce((a, o) => a + o.z, 0) / placed.length + jitter(26);
      } else {
        node.x = jitter(220);
        node.y = jitter(220);
        node.z = jitter(220);
      }
    }
  }

  _wake() {
    this._settled = false;
    this._activeFrames = 0;
    this._invalidate();
  }

  _triggerSelectPop(node) {
    this._selectAnim = { node, t0: performance.now() };
    this._invalidate();
  }

  _computeDegrees() {
    for (const n of this.nodes) n.degree = 0;
    for (const e of this.edges) {
      e.source.degree += 1;
      e.target.degree += 1;
    }
    // 1.24.0: mała mapa albo telefon bez najechania - 8 najważniejszych kul zawsze z nazwą.
    this._topLabeled = new Set([...this.nodes].filter((n) => n.degree > 0).sort((a, b) => b.degree - a.degree).slice(0, 8));
  }

  _radiusFor(node) {
    return 2.2 + Math.min(node.degree, 20) * 0.42;
  }

  // Kamera obejmująca cały graf - odpowiednik _fit() z wersji 2D, tylko
  // zamiast skali widoku liczy odległość i kierunek patrzenia.
  _fit() {
    if (this.nodes.length === 0) return;
    const box = new THREE.Box3();
    let any = false;
    for (const n of this.nodes) {
      if (!Number.isFinite(n.x)) continue;
      box.expandByPoint(new THREE.Vector3(n.x, n.y, n.z));
      any = true;
    }
    if (!any) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(40, size.length() / 2);
    const fov = (this.camera.fov * Math.PI) / 180;
    const dist = Math.min(CAMERA_MAX_DIST, Math.max(CAMERA_MIN_DIST * 2, (radius / Math.sin(fov / 2)) * 1.15));
    this._controls.target.copy(center);
    this.camera.position.set(center.x + dist * 0.42, center.y + dist * 0.32, center.z + dist * 0.84);
    this._controls.update();
  }

  // --- Symulacja siłowa 3D (siatka przestrzenna dla odpychania) ---
  _settle(iterations) {
    for (let i = 0; i < iterations; i++) this._step();
  }

  _step() {
    const grid = new Map();
    const cell = (x, y, z) => `${Math.floor(x / REPULSION_CELL_SIZE)}:${Math.floor(y / REPULSION_CELL_SIZE)}:${Math.floor(z / REPULSION_CELL_SIZE)}`;
    for (const n of this.nodes) {
      const key = cell(n.x, n.y, n.z);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }

    for (const n of this.nodes) {
      let fx = 0, fy = 0, fz = 0;
      const cx = Math.floor(n.x / REPULSION_CELL_SIZE);
      const cy = Math.floor(n.y / REPULSION_CELL_SIZE);
      const cz = Math.floor(n.z / REPULSION_CELL_SIZE);
      for (let gx = cx - 1; gx <= cx + 1; gx++) {
        for (let gy = cy - 1; gy <= cy + 1; gy++) {
          for (let gz = cz - 1; gz <= cz + 1; gz++) {
            const bucket = grid.get(`${gx}:${gy}:${gz}`);
            if (!bucket) continue;
            for (const other of bucket) {
              if (other === n) continue;
              const dx = n.x - other.x, dy = n.y - other.y, dz = n.z - other.z;
              const distSq = dx * dx + dy * dy + dz * dz || 0.01;
              const dist = Math.sqrt(distSq);
              if (dist > REPULSION_MAX_DIST) continue;
              const force = 160 / distSq;
              fx += (dx / dist) * force;
              fy += (dy / dist) * force;
              fz += (dz / dist) * force;
            }
          }
        }
      }
      fx += -n.x * 0.0022;
      fy += -n.y * 0.0022;
      fz += -n.z * 0.0022;

      n.vx = (n.vx + fx) * 0.82;
      n.vy = (n.vy + fy) * 0.82;
      n.vz = (n.vz + fz) * 0.82;
    }

    for (const e of this.edges) {
      const dx = e.target.x - e.source.x, dy = e.target.y - e.source.y, dz = e.target.z - e.source.z;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) || 0.01;
      const force = (dist - EDGE_TARGET_LEN) * 0.02;
      const fx = (dx / dist) * force, fy = (dy / dist) * force, fz = (dz / dist) * force;
      const ws = 1 / Math.sqrt(Math.max(1, e.source.degree));
      const wt = 1 / Math.sqrt(Math.max(1, e.target.degree));
      e.source.vx += fx * ws; e.source.vy += fy * ws; e.source.vz += fz * ws;
      e.target.vx -= fx * wt; e.target.vy -= fy * wt; e.target.vz -= fz * wt;
    }

    let energy = 0;
    for (const n of this.nodes) {
      const vx = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vx));
      const vy = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vy));
      const vz = Math.max(-MAX_VELOCITY, Math.min(MAX_VELOCITY, n.vz));
      n.vx = vx; n.vy = vy; n.vz = vz;
      n.x += vx; n.y += vy; n.z += vz;
      if (!Number.isFinite(n.x) || !Number.isFinite(n.y) || !Number.isFinite(n.z)) {
        n.x = (Math.random() - 0.5) * 220; n.y = (Math.random() - 0.5) * 220; n.z = (Math.random() - 0.5) * 220;
        n.vx = 0; n.vy = 0; n.vz = 0;
      }
      n.x = Math.max(-COORD_LIMIT, Math.min(COORD_LIMIT, n.x));
      n.y = Math.max(-COORD_LIMIT, Math.min(COORD_LIMIT, n.y));
      n.z = Math.max(-COORD_LIMIT, Math.min(COORD_LIMIT, n.z));
      energy += vx * vx + vy * vy + vz * vz;
    }
    return energy;
  }

  _syncMeshPositions() {
    for (const n of this.nodes) {
      if (!n._mesh) continue;
      n._mesh.position.set(n.x, n.y, n.z);
      if (n._halo) n._halo.position.copy(n._mesh.position);
    }
    for (const e of this.edges) {
      if (!e._line) continue;
      const pos = e._line.geometry.attributes.position;
      pos.setXYZ(0, e.source.x, e.source.y, e.source.z);
      pos.setXYZ(1, e.target.x, e.target.y, e.target.z);
      pos.needsUpdate = true;
      e._line.geometry.computeBoundingSphere();
    }
  }

  _visible(node) {
    return this.activeTypes.has(node.type);
  }

  _dimmed(node) {
    return this._focusSet ? !this._focusSet.has(node) : false;
  }

  _refreshFocus() {
    const sel = this.selectedNode && this._visible(this.selectedNode) ? this.selectedNode : null;
    const hov = this.hoveredNode && this._visible(this.hoveredNode) ? this.hoveredNode : null;
    const focus = sel || hov || null;
    if (focus === this._focus) return;
    this._focus = focus;
    if (!focus) {
      this._focusSet = null;
      return;
    }
    // Tryb śledzenia trasy (shift-klik, patrz _handleClick/_tracePath): zgłoszenie
    // Grzegorza (2026-10-19 rano) - podświetlone mają być węzły na trasie, BEZ
    // sąsiadów punktu STARTOWEGO (`this.selectedNode`, stały kotwica - przy
    // kolejnych shift-klikach się nie zmienia). Wcześniej doklejano sąsiadów
    // `focus` (czyli właśnie punktu startowego, patrz niżej) NAWET gdy
    // activePath nie było puste, więc przy śledzeniu trasy podświetlały się
    // dodatkowo przypadkowe węzły sąsiadujące z pierwszym kliknięciem,
    // niezwiązane z samą trasą.
    if (this.activePath.size > 0) {
      const pathSet = new Set();
      for (const id of this.activePath) {
        const n = this.byId.get(id);
        if (n) pathSet.add(n);
      }
      // Podgląd następnego kroku (zgłoszenie Grzegorza, 2026-10-19 wieczór,
      // przykład: zaznaczona Fizyka, shift-klik na Termodynamikę -> ma się
      // podświetlić to, co jest połączone z Termodynamiką, np. "Pogoda i
      // klimat"; shift-klik na "Pogoda i klimat" -> teraz podświetla się to,
      // co jest połączone Z NIĄ, np. "Geografia"). W przeciwieństwie do
      // sąsiadów punktu startowego wyżej, sąsiedzi KOŃCA trasy (`_pathFrontier`
      // - węzeł, który został shift-kliknięty jako cel, patrz _tracePath) SĄ
      // dociągane: to nie przypadkowi sąsiedzi pierwszego kliknięcia, a
      // podgląd tego, dokąd można poprowadzić trasę dalej, zanim się tam
      // kliknie. Same węzły trasy (`pathSet`) i kolor/jasność linii trasy
      // (patrz _applyVisibility: `onPath`) nie zmieniają się przez to wcale -
      // to tylko DODATKOWE węzły dopisane do zbioru "nie przyciemniaj".
      if (this._pathFrontier && this._visible(this._pathFrontier)) {
        for (const e of this.edges) {
          if (e.source === this._pathFrontier) pathSet.add(e.target);
          else if (e.target === this._pathFrontier) pathSet.add(e.source);
        }
      }
      this._focusSet = pathSet;
      return;
    }
    // Zwykłe zaznaczenie/hover (bez trasy): podświetlony węzeł + jego sąsiedzi.
    const set = new Set([focus]);
    for (const e of this.edges) {
      if (e.source === focus) set.add(e.target);
      else if (e.target === focus) set.add(e.source);
    }
    this._focusSet = set;
  }

  // Widoczność (filtr typu) + przyciemnienie (focus) + otoczka hubów +
  // kolor ścieżki - liczone tylko, gdy coś z tego faktycznie się zmieniło
  // (wołane z render(), nie z każdej klatki fizyki).
  _applyVisibility() {
    this._refreshFocus();
    const r3 = (node) => node._mesh ? this._radiusFor(node) : 0;

    for (const n of this.nodes) {
      const visible = this._visible(n);
      if (n._mesh) n._mesh.visible = visible;
      const isHub = n.degree >= 10;
      if (isHub && !n._halo && n._mesh) {
        n._halo = new THREE.Mesh(this._sphereGeo, this._haloMaterialFor(n.type));
        n._halo.position.copy(n._mesh.position);
        this.scene.add(n._halo);
      }
      if (n._halo) {
        const dim = this._dimmed(n);
        n._halo.visible = visible && isHub && !dim;
        n._halo.scale.setScalar(this._radiusFor(n) * 1.55);
      }
      if (n._mesh) {
        const dim = this._dimmed(n);
        n._mesh.scale.setScalar(this._radiusFor(n));
        n._mesh.material.opacity = 1;
        const mat = n._mesh.material;
        if (mat.transparent !== dim) { mat.transparent = dim; mat.needsUpdate = true; }
        mat.opacity = dim ? HOVER_DIM_OPACITY : 1;
      }
    }

    for (const e of this.edges) {
      if (!e._line) continue;
      const visible = this._visible(e.source) && this._visible(e.target);
      e._line.visible = visible;
      if (!visible) continue;
      const dim = this._dimmed(e.source) || this._dimmed(e.target);
      const onPath = this.activePath.has(e.source.id) && this.activePath.has(e.target.id);
      const color = onPath ? (this._cv("--accent") || "#ff4d6d") : "#ffffff";
      e._line.material.color.set(color);
      e._line.material.opacity = onPath ? 0.75 : (dim ? 0.02 : 0.14);
    }

    this._updateAuras();
    this._updateLabels();
  }

  _updateAuras() {
    const sel = this.selectedNode && this._visible(this.selectedNode) ? this.selectedNode : null;
    if (sel && sel._mesh) {
      this._auraSelected.visible = true;
      this._auraSelected.position.copy(sel._mesh.position);
      this._auraSelected.scale.setScalar(this._auraScaleFor(sel, 1.6, 1.25));
    } else {
      this._auraSelected.visible = false;
    }
    const hov = this.hoveredNode && this.hoveredNode !== sel && this._visible(this.hoveredNode) ? this.hoveredNode : null;
    if (hov && hov._mesh) {
      this._auraHover.visible = true;
      this._auraHover.position.copy(hov._mesh.position);
      this._auraHover.scale.setScalar(this._auraScaleFor(hov, 1.4, 1.15));
    } else {
      this._auraHover.visible = false;
    }
  }

  // Skala aureoli zaznaczenia/hover. Normalnie: promień węzła razy stały
  // współczynnik (factor). Węzły-huby (degree >= 10, patrz _applyVisibility)
  // mają już WŁASNĄ, permanentną poświatę `_halo` w skali 1.55x promienia -
  // zgłoszenie Grzegorza (po restarcie 1.8.2: "Matematyka się rozświetla,
  // Fizyka już nie") sprowadzało się do tego, że Fizyka jest hubem (dużo
  // połączonych notatek), a Matematyka nie. Przy starych współczynnikach
  // (1.6x zaznaczenie, 1.4x hover) aureola huba dawała ledwo 3% marginesu
  // ponad jego własne halo, a hover (1.4x < 1.55x) chował się w nim CAŁKOWICIE
  // - w ogóle się nie pokazywał. Dlatego dla huba wymuszamy margines liczony
  // od skali halo, nie od samego promienia węzła; nie-huby (większość
  // węzłów, w tym Matematyka) zachowują się dokładnie jak wcześniej.
  _auraScaleFor(node, factor, hubMarginOverHalo) {
    const base = this._radiusFor(node);
    if (node.degree >= 10) return Math.max(base * factor, base * 1.55 * hubMarginOverHalo);
    return base * factor;
  }

  // Etykiety: warstwa DOM rzutowana z 3D na ekran (camera.project), nie
  // canvas-owy tekst - prościej o ostrą, zawsze czytelną czcionkę systemową.
  // Pokazują się na hubach i na zaznaczonym/najechanym węźle.
  // 1.30.2 (zgłoszenie Grzegorza: nazwy w gęstym środku nachodziły na siebie):
  // UNIKANIE KOLIZJI 2D. Kandydaci po priorytecie (zaznaczony/najechany, potem
  // najwięcej połączeń, potem bliżej kamery); etykietę pokazujemy tylko, gdy jej
  // prostokąt nie nachodzi na już postawioną. Reszta czeka - obrót mapy i tak
  // rozsuwa węzły, więc schowana nazwa wróci, gdy zrobi się dla niej miejsce.
  _updateLabels() {
    if (!this._labelLayer) return;
    const w = window.innerWidth, h = window.innerHeight;
    const cand = [];
    for (const n of this.nodes) {
      if (!(n._mesh && n._mesh.visible && !this._dimmed(n))) continue;
      const active = n === this.selectedNode || n === this.hoveredNode;
      if (!(active || n.degree >= 10 || (this._topLabeled && this._topLabeled.has(n)))) continue;
      const v = n._mesh.position.clone().project(this.camera);
      if (v.z > 1 || v.z < -1) continue; // za kamerą / poza zasięgiem
      const x = (v.x * 0.5 + 0.5) * w;
      const y = (-v.y * 0.5 + 0.5) * h;
      if (x < -40 || x > w + 40 || y < -20 || y > h + 20) continue;
      cand.push({ n, x, y, active, z: v.z });
    }
    // Priorytet: najpierw zaznaczony/najechany, potem huby (więcej połączeń),
    // na końcu te bliżej kamery (mniejsze z). Ważne, kto "wygra" miejsce.
    cand.sort((a, b) =>
      (b.active - a.active) || (b.n.degree - a.n.degree) || (a.z - b.z));

    const placed = [];
    const keep = new Set();
    // Dwa prostokąty nachodzą na siebie (z 2 px luzu), żeby etykiety nie kleiły się bokami.
    const overlaps = (r) => placed.some((p) =>
      r.left < p.right + 2 && r.right + 2 > p.left && r.top < p.bottom + 2 && r.bottom + 2 > p.top);
    for (const c of cand) {
      const n = c.n;
      const chars = Array.from(n.title || "");
      const shown = chars.length > LABEL_MAX_CHARS ? chars.slice(0, LABEL_MAX_CHARS - 1).join("") + "…" : (n.title || "");
      // Prostokąt etykiety: wyśrodkowana nad punktem węzła (CSS translate -50% -140%).
      const bw = shown.length * 7 + 16, bh = 20;
      const left = c.x - bw / 2, top = c.y - bh * 1.4;
      const rect = { left, right: left + bw, top, bottom: top + bh };
      // Zaznaczony/najechany pokazujemy ZAWSZE (to świadomy fokus); reszta ustępuje kolizji.
      if (!c.active && overlaps(rect)) continue;
      placed.push(rect);

      let el = this._labelEl.get(n);
      if (!el) {
        el = document.createElement("span");
        el.className = "node-label-3d";
        this._labelLayer.appendChild(el);
        this._labelEl.set(n, el);
      }
      el.textContent = shown;
      el.style.transform = `translate(${c.x.toFixed(1)}px, ${c.y.toFixed(1)}px)`;
      el.classList.toggle("is-active", c.active);
      keep.add(n);
    }
    for (const [n, el] of this._labelEl) {
      if (!keep.has(n)) {
        el.remove();
        this._labelEl.delete(n);
      }
    }
  }

  _updateIdlePulse(now) {
    if (this.hoveredNode || this.selectedNode || this._pointerDown) {
      if (this.pulseEdge) { this.pulseEdge = null; this._pulseMesh.visible = false; this._invalidate(); }
      return;
    }
    if (!this.pulseEdge) { this._schedulePulse(); return; }
    this.pulseProgress += 0.02;
    if (this.pulseProgress >= 1) {
      this.pulseEdge = null;
      this._pulseMesh.visible = false;
      this._schedulePulse();
    } else if (this._visible(this.pulseEdge.source) && this._visible(this.pulseEdge.target)) {
      const s = this.pulseEdge.source, t = this.pulseEdge.target;
      this._pulseMesh.visible = true;
      this._pulseMesh.position.set(
        s.x + (t.x - s.x) * this.pulseProgress,
        s.y + (t.y - s.y) * this.pulseProgress,
        s.z + (t.z - s.z) * this.pulseProgress
      );
    }
    this._invalidate();
  }

  _schedulePulse() {
    if (this._pulseTimer || this.pulseEdge) return;
    this._pulseTimer = setTimeout(() => {
      this._pulseTimer = null;
      // 1.24.0: mapa schowana (otwarta Rozmowa) - nikt nie patrzy, nie rysujemy ~50 klatek pulsu.
      // position: fixed => offsetParent zawsze null; liczy się, czy płótno ma prostokąt na ekranie.
      const hiddenCanvas = this.canvas && this.canvas.getClientRects().length === 0;
      if (document.hidden || hiddenCanvas || this.hoveredNode || this.selectedNode || this._pointerDown) { this._schedulePulse(); return; }
      // 1.32.10 (audyt tura 14, pomiar): bez ruchu myszą/palcem dłużej niż ORBIT_IDLE_MS nikt
      // nie patrzy na ozdobny puls - co 30 s było ~170 pełnych klatek. Ruch wznawia puls.
      if (performance.now() - (this._lastInput || 0) > ORBIT_IDLE_MS) { this._schedulePulse(); return; }
      if (!this.edges.length || this.nodes.length > IDLE_PULSE_MAX_NODES) return;
      for (let i = 0; i < 12 && !this.pulseEdge; i++) {
        const e = this.edges[Math.floor(Math.random() * this.edges.length)];
        if (this._visible(e.source) && this._visible(e.target)) this.pulseEdge = e;
      }
      if (this.pulseEdge) { this.pulseProgress = 0; this._invalidate(); }
      else this._schedulePulse();
    }, IDLE_PULSE_INTERVAL_MS);
  }

  // --- Rysowanie ---
  // Klatka liczy się tylko, gdy coś się zmieniło (fizyka jeszcze się
  // układa, kamera w ruchu/dojeżdża po puszczeniu, impuls na krawędzi albo
  // puls zaznaczenia) - ten sam "śpij, gdy nic się nie dzieje" co w 2D,
  // tylko teraz warunek wznowienia woła startRenderLoop poniżej.
  render(now) {
    if (this._failed) return;
    this._updateIdlePulse(now);

    if (this._selectAnim) {
      const t = (now - this._selectAnim.t0) / SELECT_POP_MS;
      if (t >= 1) { this._selectAnim = null; this._popMesh.visible = false; }
      else {
        this._dirty = true;
        const node = this._selectAnim.node;
        if (node._mesh && this._visible(node)) {
          const ease = 1 - Math.pow(1 - t, 3);
          this._popMesh.visible = true;
          this._popMesh.position.copy(node._mesh.position);
          this._popMesh.scale.setScalar(this._radiusFor(node) * (1.3 + ease * 1.8));
          this._popMesh.material.opacity = (1 - t) * 0.5;
        } else {
          this._popMesh.visible = false;
        }
      }
    }

    if (!this._settled) {
      const energy = this._step();
      this._activeFrames += 1;
      this._dirty = true;
      if (this._activeFrames > maxActiveFrames(this.nodes.length) || energy < SETTLED_ENERGY_PER_NODE * this.nodes.length) {
        this._settled = true;
      }
      this._syncMeshPositions();
    }

    // Krążenie kamery (1.18.0, energooszczędnie - laptop bez GPU, obok liczy
    // lokalny model): ~30 klatek/s zamiast 60, a klatka, w której zmieniła się
    // TYLKO kamera, nie przelicza widoczności/przyciemnień wszystkich węzłów i
    // krawędzi (_applyVisibility), tylko pozycje etykiet. Krążenie stoi, gdy
    // jakiś węzeł jest zaznaczony (inspektor otwarty) - nie ucieka z kadru.
    const orbit = this._orbitRequested && this._autoOrbitWanted && !this.selectedNode
      && (now - this._lastInput) < ORBIT_IDLE_MS;
    this._orbitActive = orbit;
    this._controls.autoRotate = orbit;
    if (!this._dirty) {
      if (!orbit || now - this._lastOrbitFrame < ORBIT_FRAME_MS) return;
      this._lastOrbitFrame = now;
      this._orbitUpdating = true;
      try { this._controls.update(); } finally { this._orbitUpdating = false; }
      this._updateLabels();
      this.renderer.render(this.scene, this.camera);
      return;
    }
    this._dirty = false;
    this._lastOrbitFrame = now;

    this._applyVisibility();
    // Przy włączonym krążeniu update() obraca kamerę i emituje "change" -
    // bez tej flagi _wakeCamera znów ustawiałby _dirty i każda klatka krążenia
    // szła pełną (drogą) ścieżką zamiast samą kamerą (przegląd 1.18.0). Bez
    // krążenia "change" (np. wygaszanie po przeciągnięciu) ma dalej budzić klatki.
    this._orbitUpdating = orbit;
    try { this._controls.update(); } finally { this._orbitUpdating = false; }
    this.renderer.render(this.scene, this.camera);
  }

  // --- Interakcje (raycasting zamiast 2D hit-testu) ---
  _ndcFromEvent(e) {
    const rect = this.canvas.getBoundingClientRect();
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    );
  }

  _nodeAt(e) {
    const candidates = this.nodes.filter((n) => n._mesh && n._mesh.visible).map((n) => n._mesh);
    if (!candidates.length) return null;
    this._raycaster.setFromCamera(this._ndcFromEvent(e), this.camera);
    const hits = this._raycaster.intersectObjects(candidates, false);
    return hits.length ? hits[0].object.userData.node : null;
  }

  _bindEvents() {
    const canvas = this.canvas;

    const touchInput = () => { this._lastInput = performance.now(); this._invalidate(); };
    canvas.addEventListener("wheel", touchInput, { passive: true });
    canvas.addEventListener("pointerdown", touchInput);
    canvas.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      this._pointerDown = { startX: e.clientX, startY: e.clientY, moved: false };
    });

    window.addEventListener("pointermove", (e) => {
      if (this._pointerDown) {
        const dx = e.clientX - this._pointerDown.startX;
        const dy = e.clientY - this._pointerDown.startY;
        if (Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD_PX) this._pointerDown.moved = true;
        return; // w trakcie przeciągania kamery nie liczymy hover - patrz 2D
      }
      if (e.target !== canvas) {
        if (this.hoveredNode) { this.hoveredNode = null; this._invalidate(); }
        return;
      }
      const node = this._nodeAt(e);
      if (node !== this.hoveredNode) {
        this.hoveredNode = node;
        canvas.style.cursor = node ? "pointer" : "grab";
        this._invalidate();
      }
    });

    window.addEventListener("pointerup", (e) => {
      const d = this._pointerDown;
      if (!d || e.button !== 0) return;
      this._pointerDown = null;
      if (d.moved) return; // to był obrót/zoom kamery, nie klik w węzeł
      const node = this._nodeAt(e);
      if (node) this._handleClick(node, e.shiftKey);
      else this.clearSelection();
    });

    window.addEventListener("blur", () => { this._pointerDown = null; });
  }

  clearSelection() {
    if (this._failed) return;
    if (!this.selectedNode && this.activePath.size === 0) return;
    if (!this.canSelect(null)) return;
    this.selectedNode = null;
    this.activePath.clear();
    this._pathFrontier = null;
    this._focus = false;
    this._invalidate();
    this.onSelect(null);
  }

  _handleClick(node, shiftKey) {
    if (!this.canSelect(node)) return;
    if (shiftKey && this.selectedNode && this.selectedNode !== node) {
      if (!this._tracePath(this.selectedNode, node)) this.onInfo("Brak połączenia między tymi dwiema notatkami.");
    } else {
      this.selectedNode = node;
      this.activePath.clear();
      this._pathFrontier = null;
      this._triggerSelectPop(node);
    }
    this._focus = false;
    this._invalidate();
    this.onSelect(node);
  }

  _tracePath(a, b) {
    const adj = new Map();
    for (const n of this.nodes) adj.set(n.id, []);
    for (const e of this.edges) {
      adj.get(e.source.id).push(e.target.id);
      adj.get(e.target.id).push(e.source.id);
    }
    const queue = [a.id];
    let head = 0;
    const visited = new Set([a.id]);
    const prev = new Map();
    while (head < queue.length) {
      const cur = queue[head++];
      if (cur === b.id) break;
      for (const next of adj.get(cur) || []) {
        if (!visited.has(next)) {
          visited.add(next);
          prev.set(next, cur);
          queue.push(next);
        }
      }
    }
    this.activePath.clear();
    let cur = b.id;
    if (!visited.has(b.id)) { this._pathFrontier = null; return false; }
    while (cur !== undefined) {
      this.activePath.add(cur);
      cur = prev.get(cur);
    }
    // `b` to krawędź trasy shift-kliknięta JAKO CEL (nie `a`, stały punkt
    // startowy, patrz _handleClick: selectedNode się przy trasowaniu nie
    // zmienia) - czyli właśnie ten koniec, dla którego podgląd następnego
    // kroku ma sens (patrz _refreshFocus).
    this._pathFrontier = b;
    return true;
  }

  setTypeActive(type, active) {
    this._flushDeferred();
    if (this._failed) return;
    if (active) this.activeTypes.add(type);
    else this.activeTypes.delete(type);
    this._focus = false;
    this._invalidate();
  }

  /**
   * Zaznacza węzeł (z hubów, wyszukiwarki, po zapisie, ze "skoku" z
   * projektu w szynie Rozmowy). center=true przesuwa punkt, na który patrzy
   * kamera, na ten węzeł; typ ukryty filtrem jest włączany z powrotem.
   */
  focusNode(id, { center = true } = {}) {
    this._flushDeferred();
    if (this._failed) return null;
    const node = this.byId.get(id);
    if (!node) return null;
    if (!this.canSelect(node)) return null;
    if (!this.activeTypes.has(node.type)) {
      this.activeTypes.add(node.type);
      this.onTypesChanged();
    }
    this.selectedNode = node;
    this.activePath.clear();
    this._pathFrontier = null;
    this._focus = false;
    this._triggerSelectPop(node);
    if (center && node._mesh) {
      const target = node._mesh.position;
      const offset = this.camera.position.clone().sub(this._controls.target);
      // Jeśli kamera jest "zbyt blisko" (np. po mocnym przybliżeniu gdzie
      // indziej), nie każe to patrzeć z dystansu 0 - minimalny odstęp.
      if (offset.length() < CAMERA_MIN_DIST * 1.5) offset.setLength(CAMERA_MIN_DIST * 2.2);
      this._controls.target.copy(target);
      this.camera.position.copy(target).add(offset);
      this._controls.update();
      this._saveCamera();
    }
    this._invalidate();
    this.onSelect(node);
    return node;
  }
}

function startRenderLoop(graph) {
  let pending = false;
  function frame(now) {
    pending = false;
    if (graph._hidden()) return;  // schowane płótno: zero pracy; setAutoOrbit/_invalidate obudzi przy pokazaniu
    graph._flushDeferred();
    graph.render(now);
    const stillOrbiting = (graph._wakeUntil && now < graph._wakeUntil) || graph._orbitActive;
    if (!graph._settled || graph._dirty || graph.pulseEdge || graph._selectAnim || stillOrbiting) graph._requestFrame();
  }
  graph._requestFrame = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(frame);
  };
  graph._requestFrame();
}
