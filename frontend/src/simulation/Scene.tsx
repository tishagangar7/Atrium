import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  scenario,
  width,
  depth,
  elevation,
  forestEdge,
  cellAt,
} from "./terrain";
import { draw } from "./engine";
import type { Snapshot } from "./types";
export type Layer = "landscape" | "fuel" | "heat";
type Props = {
  snapshot: Snapshot;
  layer: Layer;
  selected: number | null;
  onSelect: (id: number) => void;
  cameraMode: "orbit" | "top";
  resetCamera: number;
};
export function Scene({
  snapshot,
  layer,
  selected,
  onSelect,
  cameraMode,
  resetCamera,
}: Props) {
  const host = useRef<HTMLDivElement>(null);
  const latest = useRef({
    snapshot,
    layer,
    selected,
    onSelect,
    cameraMode,
    resetCamera,
  });
  latest.current = {
    snapshot,
    layer,
    selected,
    onSelect,
    cameraMode,
    resetCamera,
  };
  const [failure, setFailure] = useState("");
  useEffect(() => {
    const container = host.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch {
      setFailure(
        "WebGL is unavailable. Enable hardware acceleration to explore the 3D terrain. Simulation controls and metrics still work.",
      );
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.55;
    container.appendChild(renderer.domElement);
    renderer.domElement.setAttribute(
      "aria-label",
      "Interactive 3D forest. Drag to orbit, scroll to zoom, click terrain to inspect.",
    );
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2("#111e25", 0.0007);
    const camera = new THREE.PerspectiveCamera(39, 1, 1, 1800);
    camera.position.set(285, 260, 350);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 13, -5);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.maxPolarAngle = Math.PI / 2.15;
    controls.minDistance = 100;
    controls.maxDistance = 900;
    scene.add(new THREE.HemisphereLight("#c6e5e6", "#3b3027", 2.1));
    const sun = new THREE.DirectionalLight("#ffe3ab", 3.5);
    sun.position.set(-130, 300, 160);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -240;
    sun.shadow.camera.right = 240;
    sun.shadow.camera.top = 220;
    sun.shadow.camera.bottom = -220;
    sun.shadow.camera.far = 650;
    sun.shadow.normalBias = 0.6;
    scene.add(sun);
    const material = (color: string, roughness = 1) =>
      new THREE.MeshStandardMaterial({ color, roughness });
    const soil = new THREE.Mesh(
      new THREE.BoxGeometry(width, 3, depth),
      material("#382f28"),
    );
    soil.position.y = -10.5;
    soil.receiveShadow = true;
    scene.add(soil);
    const rim = new THREE.Mesh(
      new THREE.BoxGeometry(width + 3, 2, depth + 3),
      material("#53655f"),
    );
    rim.position.y = -13;
    scene.add(rim);
    const groundGeometry = new THREE.PlaneGeometry(
      width,
      depth,
      scenario.columns * 2,
      scenario.rows * 2,
    );
    groundGeometry.rotateX(-Math.PI / 2);
    const positions = groundGeometry.attributes.position;
    const colors = new Float32Array(positions.count * 3);
    const color = new THREE.Color();
    for (let i = 0; i < positions.count; i++) {
      const x = positions.getX(i),
        z = positions.getZ(i);
      positions.setY(i, elevation(x, z));
      const id = cellAt(
        Math.min(x, width / 2 - 0.01),
        Math.min(z, depth / 2 - 0.01),
      );
      const kind = latest.current.snapshot.cells[id]?.kind;
      color.set(
        kind === "forest"
          ? "#334d38"
          : kind === "scrub"
            ? "#777449"
            : kind === "cleared"
              ? "#8f8d73"
              : "#a7a367",
      );
      color.multiplyScalar(0.9 + draw(42, 0, `ground${i}`) * 0.2);
      color.toArray(colors, i * 3);
    }
    groundGeometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    groundGeometry.computeVertexNormals();
    const ground = new THREE.Mesh(
      groundGeometry,
      new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 1 }),
    );
    ground.receiveShadow = true;
    scene.add(ground);
    // Close the terrain perimeter to the base with individual, sloped walls.
    const edgePoints: [number, number][] = [];
    for (let x = -width / 2; x <= width / 2; x += 8)
      edgePoints.push([x, -depth / 2]);
    for (let z = -depth / 2 + 8; z <= depth / 2; z += 8)
      edgePoints.push([width / 2, z]);
    for (let x = width / 2 - 8; x >= -width / 2; x -= 8)
      edgePoints.push([x, depth / 2]);
    for (let z = depth / 2 - 8; z >= -depth / 2; z -= 8)
      edgePoints.push([-width / 2, z]);
    const wallVertices: number[] = [];
    edgePoints.forEach(([x, z], i) => {
      const [nx, nz] = edgePoints[(i + 1) % edgePoints.length];
      wallVertices.push(
        x,
        -9,
        z,
        nx,
        -9,
        nz,
        nx,
        elevation(nx, nz),
        nz,
        x,
        -9,
        z,
        nx,
        elevation(nx, nz),
        nz,
        x,
        elevation(x, z),
        z,
      );
    });
    const wallGeo = new THREE.BufferGeometry();
    wallGeo.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(wallVertices, 3),
    );
    wallGeo.computeVertexNormals();
    const wall = new THREE.Mesh(
      wallGeo,
      new THREE.MeshStandardMaterial({
        color: "#5a4938",
        side: THREE.DoubleSide,
      }),
    );
    scene.add(wall);
    const dummy = new THREE.Object3D();
    const treeCells: number[] = [];
    const treePositions: { x: number; z: number; h: number }[] = [];
    for (let i = 0; i < 540; i++) {
      const x = (draw(42, 0, `tx${i}`) - 0.5) * (width - 8),
        z = (draw(42, 0, `tz${i}`) - 0.5) * (depth - 8);
      if (z > forestEdge(x) - 2) continue;
      treePositions.push({ x, z, h: 17 + draw(42, 0, `th${i}`) * 23 });
      treeCells.push(cellAt(x, z));
    }
    const trunks = new THREE.InstancedMesh(
      new THREE.CylinderGeometry(0.45, 1.05, 1, 6),
      material("#6e4330"),
      treePositions.length,
    );
    const crowns = new THREE.InstancedMesh(
      new THREE.ConeGeometry(1, 1, 7),
      material("#47744f"),
      treePositions.length * 3,
    );
    trunks.castShadow = true;
    crowns.castShadow = true;
    crowns.receiveShadow = true;
    treePositions.forEach((t, i) => {
      const y = elevation(t.x, t.z);
      dummy.position.set(t.x, y + t.h / 2, t.z);
      dummy.scale.set(1, t.h, 1);
      dummy.updateMatrix();
      trunks.setMatrixAt(i, dummy.matrix);
      for (let k = 0; k < 3; k++) {
        const r = ((6.1 - k * 1.35) * t.h) / 30;
        dummy.position.set(t.x, y + t.h * (0.49 + k * 0.19), t.z);
        dummy.scale.set(r, t.h * 0.52, r);
        dummy.updateMatrix();
        crowns.setMatrixAt(i * 3 + k, dummy.matrix);
        crowns.setColorAt(
          i * 3 + k,
          new THREE.Color(["#325e43", "#457657", "#5b8561"][k]),
        );
      }
    });
    scene.add(trunks, crowns);
    const roadPoints = Array.from({ length: 41 }, (_, i) => {
      const x = -width / 2 + i * 8;
      return new THREE.Vector3(
        x,
        elevation(x, scenario.road.z) + 0.4,
        scenario.road.z,
      );
    });
    const road = new THREE.Mesh(
      new THREE.TubeGeometry(
        new THREE.CatmullRomCurve3(roadPoints),
        80,
        3.4,
        4,
        false,
      ),
      material("#727b76"),
    );
    road.scale.y = 0.995;
    scene.add(road);
    const route = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(
        roadPoints.map((p) => new THREE.Vector3(p.x, p.y + 1, p.z)),
      ),
      new THREE.LineDashedMaterial({
        color: "#e6dcb8",
        dashSize: 4,
        gapSize: 4,
      }),
    );
    route.computeLineDistances();
    scene.add(route);
    scenario.buildings.forEach((b) => {
      const group = new THREE.Group();
      group.position.set(b.x, elevation(b.x, b.z), b.z);
      const block = new THREE.Mesh(
        new THREE.BoxGeometry(b.width, b.height, b.depth),
        material("#d6c6a9"),
      );
      block.position.y = b.height / 2;
      block.castShadow = true;
      block.receiveShadow = true;
      const roof = new THREE.Mesh(
        new THREE.BoxGeometry(b.width + 2, 1.5, b.depth + 2),
        material("#788589"),
      );
      roof.position.y = b.height + 0.5;
      group.add(block, roof);
      for (let x = -b.width / 2 + 3; x < b.width / 2 - 2; x += 5) {
        const window = new THREE.Mesh(
          new THREE.BoxGeometry(2.7, 3, 0.2),
          material("#4e7576"),
        );
        window.position.set(x, b.height * 0.6, b.depth / 2 + 0.1);
        group.add(window);
      }
      scene.add(group);
    });
    function label(text: string, x: number, z: number, tint = "#c8e1d9") {
      const canvas = document.createElement("canvas");
      canvas.width = 768;
      canvas.height = 96;
      const ctx = canvas.getContext("2d")!;
      ctx.fillStyle = "#10221fe0";
      ctx.roundRect(0, 0, 768, 96, 20);
      ctx.fill();
      ctx.font = "500 34px sans-serif";
      ctx.fillStyle = tint;
      ctx.textAlign = "center";
      ctx.fillText(text, 384, 60);
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: texture,
          depthTest: false,
          transparent: true,
        }),
      );
      sprite.position.set(x, elevation(x, z) + 15, z);
      sprite.scale.set(77, 9.6, 1);
      scene.add(sprite);
    }
    label("REDWOOD FOREST", -63, -103);
    label("GREAT MEADOW", -36, 90);
    label("MUSIC CENTER", 89, 71);
    const fire = new THREE.InstancedMesh(
      new THREE.ConeGeometry(2.8, 1, 7),
      new THREE.MeshBasicMaterial({
        color: "#ff8b32",
        transparent: true,
        opacity: 0.9,
      }),
      snapshot.cells.length,
    );
    const core = new THREE.InstancedMesh(
      new THREE.ConeGeometry(1.7, 1, 6),
      new THREE.MeshBasicMaterial({ color: "#ffe7a4" }),
      snapshot.cells.length,
    );
    const overlay = new THREE.InstancedMesh(
      new THREE.PlaneGeometry(7.8, 7.8).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.65,
        depthWrite: false,
      }),
      snapshot.cells.length,
    );
    const smoke = new THREE.InstancedMesh(
      new THREE.IcosahedronGeometry(1, 1),
      new THREE.MeshStandardMaterial({
        color: "#a8ada6",
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
      }),
      330,
    );
    smoke.frustumCulled = false;
    fire.frustumCulled = false;
    core.frustumCulled = false;
    overlay.frustumCulled = false;
    scene.add(fire, core, overlay, smoke);
    const emberGeometry = new THREE.BufferGeometry();
    const emberPositions = new Float32Array(scenario.physics.maxEmbers * 3);
    emberGeometry.setAttribute(
      "position",
      new THREE.BufferAttribute(emberPositions, 3),
    );
    const emberPoints = new THREE.Points(
      emberGeometry,
      new THREE.PointsMaterial({
        color: "#ffc77b",
        size: 1.5,
        transparent: true,
      }),
    );
    emberPoints.frustumCulled = false;
    scene.add(emberPoints);
    const selection = new THREE.Mesh(
      new THREE.RingGeometry(4, 4.5, 32).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: "#b6ffdc", side: THREE.DoubleSide }),
    );
    scene.add(selection);
    const arrow = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(-125, 65, 75),
      29,
      "#bef6df",
      7,
      4,
    );
    scene.add(arrow);
    const raycaster = new THREE.Raycaster();
    let startX = 0,
      startY = 0;
    const pointerDown = (e: PointerEvent) => {
      startX = e.clientX;
      startY = e.clientY;
    };
    const pointerUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - startX, e.clientY - startY) > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((e.clientX - rect.left) / rect.width) * 2 - 1,
          (-(e.clientY - rect.top) / rect.height) * 2 + 1,
        ),
        camera,
      );
      const hit = raycaster.intersectObject(ground)[0];
      if (hit) {
        const id = cellAt(hit.point.x, hit.point.z);
        if (id >= 0) latest.current.onSelect(id);
      }
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    let fitScale = 1;
    const resize = new ResizeObserver(() => {
      const w = container.clientWidth,
        h = container.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      const nextScale = Math.max(1, Math.min(2, 1.25 / camera.aspect));
      camera.position
        .sub(controls.target)
        .multiplyScalar(nextScale / fitScale)
        .add(controls.target);
      fitScale = nextScale;
      camera.updateProjectionMatrix();
    });
    resize.observe(container);
    let frame = 0,
      lastVersion = -1,
      lastLayer = "",
      lastMode = "",
      lastReset = -1;
    const animate = (time: number) => {
      const {
        snapshot: s,
        layer: currentLayer,
        selected: id,
        cameraMode: mode,
        resetCamera: reset,
      } = latest.current;
      if (mode !== lastMode || reset !== lastReset) {
        if (mode === "top") camera.position.set(0, 520 * fitScale, 1);
        else
          camera.position.set(285 * fitScale, 260 * fitScale, 350 * fitScale);
        controls.target.set(0, 13, -5);
        lastMode = mode;
        lastReset = reset;
      }
      if (s.state_version !== lastVersion || currentLayer !== lastLayer) {
        s.cells.forEach((c, i) => {
          dummy.position.set(c.x, c.elevation + 0.7, c.z);
          dummy.scale.set(1, 1, 1);
          dummy.updateMatrix();
          overlay.setMatrixAt(i, dummy.matrix);
          color.set(
            currentLayer === "heat"
              ? c.intensity > 0
                ? "#ff5c25"
                : c.burned
                  ? "#3c2c2a"
                  : "#315a52"
              : currentLayer === "fuel"
                ? c.kind === "forest"
                  ? "#399b82"
                  : c.kind === "scrub"
                    ? "#e28c45"
                    : c.kind === "grass"
                      ? "#d0be57"
                      : "#78868a"
                : c.suppressed
                  ? "#68d5bd"
                  : c.burned
                    ? "#392921"
                    : "#ffffff",
          );
          if (currentLayer === "landscape" && !c.burned && !c.suppressed) {
            dummy.scale.set(0, 0, 0);
            dummy.updateMatrix();
            overlay.setMatrixAt(i, dummy.matrix);
          }
          overlay.setColorAt(i, color);
        });
        overlay.instanceMatrix.needsUpdate = true;
        if (overlay.instanceColor) overlay.instanceColor.needsUpdate = true;
        treeCells.forEach((cell, i) => {
          const c = s.cells[cell];
          for (let k = 0; k < 3; k++)
            crowns.setColorAt(
              i * 3 + k,
              color.set(
                c.burned
                  ? c.intensity
                    ? "#805833"
                    : "#3b3830"
                  : ["#325e43", "#457657", "#5b8561"][k],
              ),
            );
        });
        if (crowns.instanceColor) crowns.instanceColor.needsUpdate = true;
        (road.material as THREE.MeshStandardMaterial).color.set(
          s.roadClosed ? "#a4493c" : "#727b76",
        );
        lastVersion = s.state_version;
        lastLayer = currentLayer;
      }
      let count = 0,
        smokeCount = 0;
      const a = (s.weather.windToward * Math.PI) / 180;
      const windX = Math.sin(a),
        windZ = -Math.cos(a);
      arrow.setDirection(new THREE.Vector3(windX, 0, windZ));
      for (const c of s.cells)
        if (c.intensity > 0) {
          const h =
            (3 + c.intensity * 3) * (0.85 + 0.15 * Math.sin(time / 120 + c.id));
          dummy.position.set(c.x, c.elevation + h / 2, c.z);
          dummy.scale.set(1, h, 1);
          dummy.rotation.z = -windX * 0.18;
          dummy.rotation.x = windZ * 0.18;
          dummy.updateMatrix();
          fire.setMatrixAt(count, dummy.matrix);
          dummy.scale.set(0.8, h * 0.6, 0.8);
          dummy.position.y = c.elevation + h * 0.3;
          dummy.updateMatrix();
          core.setMatrixAt(count++, dummy.matrix);
          dummy.rotation.set(0, 0, 0);
          if (smokeCount < 330) {
            for (let k = 0; k < 3 && smokeCount < 330; k++) {
              const phase = (time / 12000 + c.id * 0.127 + k / 3) % 1,
                lift = 9 + phase * 42;
              dummy.position.set(
                c.x + phase * windX * s.weather.windSpeed * 4,
                c.elevation + lift,
                c.z + phase * windZ * s.weather.windSpeed * 4,
              );
              dummy.scale.setScalar(3 + phase * 9);
              dummy.updateMatrix();
              smoke.setMatrixAt(smokeCount++, dummy.matrix);
            }
          }
        }
      fire.count = core.count = count;
      smoke.count = smokeCount;
      fire.instanceMatrix.needsUpdate =
        core.instanceMatrix.needsUpdate =
        smoke.instanceMatrix.needsUpdate =
          true;
      s.embers.forEach((e, i) => {
        emberPositions[i * 3] = e.x;
        emberPositions[i * 3 + 1] = e.y;
        emberPositions[i * 3 + 2] = e.z;
      });
      emberGeometry.setDrawRange(0, s.embers.length);
      emberGeometry.attributes.position.needsUpdate = true;
      const selectedCell = id === null ? undefined : s.cells[id];
      selection.visible = !!selectedCell;
      if (selectedCell)
        selection.position.set(
          selectedCell.x,
          selectedCell.elevation + 0.9,
          selectedCell.z,
        );
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        mesh.geometry?.dispose();
        const materials = mesh.material
          ? Array.isArray(mesh.material)
            ? mesh.material
            : [mesh.material]
          : [];
        for (const mat of materials) {
          (mat as THREE.MeshBasicMaterial).map?.dispose();
          mat.dispose();
        }
      });
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);
  return (
    <div className="world-canvas" ref={host}>
      {failure && (
        <div className="webgl-error" role="alert">
          {failure}
        </div>
      )}
    </div>
  );
}
