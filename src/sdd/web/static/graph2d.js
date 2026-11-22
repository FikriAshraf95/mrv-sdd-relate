// The 2D graph: Cytoscape, same view interface as graph3d.js. Also the fallback without WebGL.
// create(host, {onSelect, onExpand}) -> view with set, setShown, search, select, reset, restyle, destroy.
import { LABELS, h } from "./dom.js";
import { ZOOM, cyStyle, declutter, elementsOf, smoothZoom } from "./cystyle.js";

export function create(host, cb) {
  const box = h("div", { id: "cy" });
  host.append(box);
  const cy = cytoscape({ container: box, elements: [], style: cyStyle(), ...ZOOM });
  smoothZoom(cy);
  let shown = null;
  cy.on("tap", "node", (e) => cb.onSelect(e.target.id()));
  cy.on("dbltap", "node", (e) => cb.onExpand(e.target.id()));

  function applyFilter() {
    cy.nodes().forEach((n) => n.toggleClass("hidden", !!shown && LABELS.includes(n.data("label")) && !shown.has(n.data("label"))));
  }

  return {
    set(nodes, edges) {
      const selected = cy.$("node:selected").id();
      cy.elements().remove();
      cy.add(elementsOf({ nodes, edges }));
      applyFilter();
      // Spread, not squeeze: strong repulsion and long springs so nodes keep apart. cose is slow on a
      // big graph, so it gets fewer iterations; a huge one gets the cheap concentric layout.
      const n = nodes.length;
      const layout =
        n > 1500
          ? { name: "concentric", minNodeSpacing: 14 }
          : {
              name: "cose",
              animate: false,
              randomize: true,
              numIter: n > 150 ? 450 : 800,
              nodeRepulsion: () => 25000 + 150 * Math.min(n, 400), // a bigger graph does not need a wider one
              idealEdgeLength: () => 45,
              edgeElasticity: () => 80,
              nodeOverlap: 30,
              gravity: 0.15,
              componentSpacing: 40,
              nestingFactor: 1,
            };
      declutter(cy);
      cy.layout({ ...layout, fit: true, padding: 30 }).run();
      if (selected) cy.getElementById(selected).select();
    },
    setShown(labels) {
      shown = labels;
      applyFilter();
    },
    search(q) {
      q = q.trim().toLowerCase();
      cy.nodes().removeClass("hit");
      if (!q) return 0;
      const exact = cy.nodes().filter((n) => n.id().toLowerCase() === q); // an exact ID marks only itself
      const hits = exact.nonempty()
        ? exact
        : cy.nodes().filter((n) => n.id().toLowerCase().includes(q) || String(n.data("title")).toLowerCase().includes(q));
      hits.addClass("hit");
      if (hits.nonempty()) cy.animate({ fit: { eles: hits, padding: 60 }, duration: 200 });
      return hits.length;
    },
    select(id) {
      cy.$(":selected").unselect();
      const n = cy.getElementById(id);
      if (n.nonempty()) n.select();
    },
    reset() {
      cy.nodes().removeClass("hit");
      cy.fit(undefined, 24);
    },
    restyle: () => cy.style(cyStyle()),
    destroy: () => cy.destroy(),
    count: () => ({ nodes: cy.nodes().length, edges: cy.edges().length }),
  };
}
