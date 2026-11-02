(function () {
  'use strict';
  const VS = `#version 300 es
  in vec2 aPos;
  void main(){ gl_Position = vec4(aPos, 0.0, 1.0); }`;

  const FS = `#version 300 es
  precision highp float;
  out vec4 fragColor;
  uniform vec2 uRes;
  uniform vec3 uCamPos, uCamFwd, uCamRight, uCamUp;
  uniform float uAspect, uTanHalf, uTime, uWaterY;
  uniform vec3 uSunDir;
  uniform int uCount;
  uniform vec3 uBPos[12];
  uniform vec4 uBQuat[12];
  uniform float uBScale[12];
  uniform vec3 uBColor[12];
  uniform vec3 uPPos[12];
  uniform vec4 uPQuat[12];
  uniform float uPScale[12];

  struct Hit { bool hit; float t; vec3 p; vec3 n; int mat; int obj; };

  vec3 qrot(vec4 q, vec3 v) {
    return v + 2.0 * cross(q.xyz, cross(q.xyz, v) + q.w * v);
  }
  float sdCyl(vec3 p, float r, float h) {
    vec2 d = vec2(length(p.xz) - r, abs(p.y) - h);
    return min(max(d.x, d.y), 0.0) + length(max(d, 0.0));
  }
  float sdOuter(vec3 p) {
    float body = sdCyl(p, .20, .34);
    float bottom = length(p - vec3(0., -.34, 0.)) - .19;
    float shoulder = sdCyl(p - vec3(0., .39, 0.), .115, .07);
    float neck = sdCyl(p - vec3(0., .50, 0.), .085, .09);
    return min(min(body, bottom), min(shoulder, neck));
  }
  float sdInner(vec3 p) {
    float body = sdCyl(p, .178, .315);
    float bottom = length(p - vec3(0., -.32, 0.)) - .17;
    float shoulder = sdCyl(p - vec3(0., .38, 0.), .092, .055);
    float neck = sdCyl(p - vec3(0., .49, 0.), .064, .10);
    return min(min(body, bottom), min(shoulder, neck));
  }
  float sdShell(vec3 p) { return max(sdOuter(p), -sdInner(p)); }
  float sdCork(vec3 p) { return sdCyl(p - vec3(0., .62, 0.), .087, .065); }
  float sdLabel(vec3 p) { return max(abs(sdCyl(p - vec3(0., .04, 0.), .207, .070)) - .004, -.01); }
  float sdPaperLocal(vec3 p) { return sdCyl(p, .058, .16); }
  float sdPaperWorld(vec3 world, int i) {
    vec4 q = uPQuat[i]; vec4 qinv = vec4(-q.xyz, q.w);
    float s = max(uPScale[i], .001);
    vec3 lp = qrot(qinv, (world - uPPos[i]) / s);
    return sdPaperLocal(lp) * s;
  }
  float waveH(vec2 p, float t) {
    return .085 * sin(dot(p, vec2(.93, .37)) * 1.15 - t * 1.05)
         + .060 * sin(dot(p, vec2(-.52, .85)) * 1.85 - t * 1.35)
         + .042 * sin(dot(p, vec2(.31, -.95)) * 2.65 - t * 1.65);
  }
  vec3 waterNormal(vec2 p, float t) {
    float e = .035;
    float h = waveH(p, t);
    float hx = waveH(p + vec2(e, 0.), t);
    float hz = waveH(p + vec2(0., e), t);
    return normalize(vec3(-(hx - h) / e, 1.0, -(hz - h) / e));
  }
  vec3 sky(vec3 d) {
    float h = clamp(d.y * 1.2 + .035, 0.0, 1.0);
    vec3 col = mix(vec3(.58, .79, .82), vec3(.10, .38, .58), pow(h, .72));
    float s = max(dot(normalize(d), uSunDir), 0.0);
    col += vec3(1.0, .82, .46) * pow(s, 260.0) * 2.2;
    col += vec3(1.0, .85, .55) * pow(s, 18.0) * .08;
    return col;
  }
  vec3 bottleNormal(vec3 world, int i, int mat) {
    vec4 q = uBQuat[i]; vec4 qinv = vec4(-q.xyz, q.w);
    float s = max(uBScale[i], .001);
    vec3 lp = qrot(qinv, (world - uBPos[i]) / s);
    vec3 e = vec3(.003, 0., 0.), n;
    if (mat == 2) {
      vec4 pq = uPQuat[i], pqinv = vec4(-pq.xyz, pq.w);
      float ps = max(uPScale[i], .001);
      vec3 pp = qrot(pqinv, (world - uPPos[i]) / ps);
      n = vec3(
        sdPaperLocal(pp + e) - sdPaperLocal(pp - e),
        sdPaperLocal(pp + vec3(0.,.003,0.)) - sdPaperLocal(pp - vec3(0.,.003,0.)),
        sdPaperLocal(pp + vec3(0.,0.,.003)) - sdPaperLocal(pp - vec3(0.,0.,.003))
      );
      return normalize(qrot(pq, n));
    }
    if (mat == 3) {
      n = vec3(sdCork(lp+e)-sdCork(lp-e), sdCork(lp+vec3(0.,.003,0.))-sdCork(lp-vec3(0.,.003,0.)), sdCork(lp+vec3(0.,0.,.003))-sdCork(lp-vec3(0.,0.,.003)));
    } else if (mat == 4) {
      n = vec3(sdLabel(lp+e)-sdLabel(lp-e), sdLabel(lp+vec3(0.,.003,0.))-sdLabel(lp-vec3(0.,.003,0.)), sdLabel(lp+vec3(0.,0.,.003))-sdLabel(lp-vec3(0.,0.,.003)));
    } else {
      n = vec3(sdShell(lp+e)-sdShell(lp-e), sdShell(lp+vec3(0.,.003,0.))-sdShell(lp-vec3(0.,.003,0.)), sdShell(lp+vec3(0.,0.,.003))-sdShell(lp-vec3(0.,0.,.003)));
    }
    return normalize(qrot(q, n));
  }
  Hit intersect(vec3 ro, vec3 rd) {
    Hit h; h.hit = false; h.t = 1e9; h.mat = -1; h.obj = -1;
    const float MAX_T = 24.0;
    if (rd.y < 0.0 && ro.y > uWaterY) {
      float tw = (uWaterY - ro.y) / rd.y;
      if (tw > 0.0 && tw < MAX_T) { h.hit = true; h.t = tw; h.p = ro + rd * tw; h.n = waterNormal(h.p.xz, uTime); h.mat = 1; }
    }
    float t = .02;
    for (int step = 0; step < 40; step++) {
      if (t > h.t || t > MAX_T) break;
      vec3 p = ro + rd * t;
      float best = 1e9; int bi = -1, bm = -1;
      for (int i = 0; i < 12; i++) {
        if (i >= uCount) break;
        vec4 q = uBQuat[i]; vec4 qinv = vec4(-q.xyz, q.w);
        float s = max(uBScale[i], .001);
        float bound = length(p - uBPos[i]) - s * .78;
        if (bound > best) continue;
        if (bound > .10) { if (bound < best) best = bound; continue; }
        vec3 lp = qrot(qinv, (p - uBPos[i]) / s);
        float ds = sdShell(lp) * s; if (ds < best) { best = ds; bi = i; bm = 0; }
        float dc = sdCork(lp) * s; if (dc < best) { best = dc; bi = i; bm = 3; }
        float dl = sdLabel(lp) * s; if (dl < best) { best = dl; bi = i; bm = 4; }
        float dp = sdPaperWorld(p, i); if (dp < best) { best = dp; bi = i; bm = 2; }
      }
      if (best < .0015 && t < h.t) {
        h.hit = true; h.t = t; h.p = p; h.n = bottleNormal(p, bi, bm); h.mat = bm; h.obj = bi;
        return h;
      }
      t += clamp(best * .45, .006, .22);
    }
    return h;
  }
  float fresnel(float cosi, float eta) {
    float r0 = pow((1.0 - eta) / (1.0 + eta), 2.0);
    return r0 + (1.0 - r0) * pow(1.0 - cosi, 5.0);
  }
  // one-bounce reflection sample: makes bottle/water reflections actually visible
  // without recursive paths or increasing the fixed render radius.
  vec3 traceOne(vec3 ro, vec3 rd) {
    Hit h = intersect(ro, rd);
    if (!h.hit) return sky(rd);
    if (h.mat == 1) {
      float F = fresnel(clamp(dot(-rd, h.n), 0.0, 1.0), 1.33);
      return mix(vec3(.025, .15, .20), sky(reflect(rd, h.n)), F * .9);
    }
    if (h.mat == 0) {
      vec3 n = h.n;
      if (dot(rd, n) > 0.0) n = -n;
      return mix(vec3(.55, .75, .82), sky(reflect(rd, n)), .72) + uBColor[h.obj] * .10;
    }
    vec3 base;
    if (h.mat == 2) base = vec3(.96, .88, .67);
    else if (h.mat == 3) base = vec3(.46, .28, .16);
    else base = uBColor[h.obj];
    float diff = max(dot(normalize(h.n), uSunDir), 0.0);
    return base * (.23 + .77 * diff) + vec3(.14) * pow(diff, 24.0);
  }
  vec3 trace(vec3 ro, vec3 rd) {
    vec3 col = vec3(0.0), thru = vec3(1.0);
    for (int bounce = 0; bounce < 3; bounce++) {
      Hit h = intersect(ro, rd);
      if (!h.hit) { col += thru * sky(rd); break; }
      if (h.mat == 1) {
        vec3 n = h.n;
        float cosi = clamp(dot(-rd, n), 0.0, 1.0);
        float F = fresnel(cosi, 1.33);
        vec3 reflDir = reflect(rd, n);
        col += thru * min(1.0, F * 1.8 + .06) * traceOne(h.p + n * .012, reflDir);
        col += thru * (1.0 - F) * vec3(.025, .16, .22) * 1.1;
        vec3 rr = refract(rd, n, 1.0 / 1.33);
        if (dot(rr, rr) < 1e-5) rd = reflect(rd, n);
        else { rd = normalize(rr); ro = h.p + rd * .012; thru *= .22; }
        continue;
      }
      if (h.mat == 0) {
        vec3 n = h.n;
        bool outside = dot(rd, n) < 0.0;
        if (!outside) n = -n;
        float eta = outside ? 1.0 / 1.5 : 1.5;
        float cosi = clamp(dot(-rd, n), 0.0, 1.0);
        float F = fresnel(cosi, eta);
        vec3 rr = refract(rd, n, eta);
        vec3 reflDir = reflect(rd, n);
        if (dot(rr, rr) < 1e-5) {
          // total internal reflection: remain inside the glass
          col += thru * traceOne(h.p + n * .012, reflDir) * .18;
          rd = reflDir;
          ro = h.p + rd * .010;
        } else {
          float reflAmt = min(1.0, F * 1.9 + .07);
          vec3 reflected = traceOne(h.p + n * .012, reflDir);
          col += thru * reflAmt * reflected;
          // sun glint on the glass
          col += thru * pow(max(dot(reflDir, uSunDir), 0.0), 80.0) * vec3(1.0, .88, .62) * 1.6;
          col += thru * (1.0 - F) * vec3(.42, .62, .68) * .20;
          thru *= (1.0 - F) * mix(vec3(.93, .99, 1.0), uBColor[h.obj], .10);
          rd = normalize(rr);
          ro = h.p + rd * .010;
        }
        continue;
      }
      vec3 base;
      if (h.mat == 2) base = vec3(.96, .88, .67);
      else if (h.mat == 3) base = vec3(.46, .28, .16);
      else base = uBColor[h.obj];
      float diff = max(dot(normalize(h.n), uSunDir), 0.0);
      col += thru * (base * (.23 + .77 * diff) + vec3(.16) * pow(diff, 24.0));
      break;
    }
    return col;
  }
  void main() {
    vec2 uv = (gl_FragCoord.xy / uRes) * 2.0 - 1.0;
    uv.x *= uAspect;
    vec3 rd = normalize(uCamFwd + uCamRight * uv.x * uTanHalf + uCamUp * uv.y * uTanHalf);
    vec3 c = trace(uCamPos, rd);
    c = pow(max(c, 0.0), vec3(1.0 / 2.2));
    fragColor = vec4(c, 1.0);
  }`;

  window.KPBottleRay = function (canvas, state) {
    const gl = canvas.getContext('webgl2', { alpha: true, antialias: false, premultipliedAlpha: false });
    if (!gl) return null;
    function shader(type, src) {
      const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.error(gl.getShaderInfoLog(s)); return null; }
      return s;
    }
    const vs = shader(gl.VERTEX_SHADER, VS), fs = shader(gl.FRAGMENT_SHADER, FS);
    if (!vs || !fs) return null;
    const prog = gl.createProgram(); gl.attachShader(prog, vs); gl.attachShader(prog, fs); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) { console.error(gl.getProgramInfoLog(prog)); return null; }
    gl.useProgram(prog);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "aPos"); gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = {};
    for (const n of ["uRes","uCamPos","uCamFwd","uCamRight","uCamUp","uAspect","uTanHalf","uTime","uWaterY","uSunDir","uCount","uBPos","uBQuat","uBScale","uBColor","uPPos","uPQuat","uPScale"]) u[n] = gl.getUniformLocation(prog, n);
    const p = new Float32Array(36), q = new Float32Array(48), s = new Float32Array(12), c = new Float32Array(36), pp = new Float32Array(36), pq = new Float32Array(48), ps = new Float32Array(12);
    const tmp = new THREE.Vector3(), fwd = new THREE.Vector3(), right = new THREE.Vector3(), up = new THREE.Vector3(), target = new THREE.Vector3(0, .35, 0);
    let w = 0, h = 0;
    function resize() {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const nw = Math.max(320, Math.round(r.width * .50)), nh = Math.max(180, Math.round(r.height * .50));
      if (nw !== w || nh !== h) { w = canvas.width = nw; h = canvas.height = nh; }
    }
    function render(st) {
      resize();
      gl.viewport(0, 0, w, h);
      const cam = st.camera;
      fwd.copy(target).sub(cam.position).normalize();
      right.crossVectors(fwd, new THREE.Vector3(0, 1, 0)).normalize();
      up.crossVectors(right, fwd).normalize();
      gl.uniform2f(u.uRes, w, h);
      gl.uniform3fv(u.uCamPos, cam.position.toArray());
      gl.uniform3fv(u.uCamFwd, fwd.toArray());
      gl.uniform3fv(u.uCamRight, right.toArray());
      gl.uniform3fv(u.uCamUp, up.toArray());
      gl.uniform1f(u.uAspect, w / h);
      gl.uniform1f(u.uTanHalf, Math.tan(THREE.MathUtils.degToRad(cam.fov) * .5));
      gl.uniform1f(u.uTime, st.t || 0);
      gl.uniform1f(u.uWaterY, -0.27);
      gl.uniform3f(u.uSunDir, -0.55, 0.72, 0.42);
      const bs = st.bodies.slice(0, 12);
      p.fill(0); q.fill(0); s.fill(1); c.fill(1); pp.fill(0); pq.fill(0); ps.fill(1);
      bs.forEach((o, i) => {
        const b = o.body;
        p[i*3] = b.position.x; p[i*3+1] = b.position.y; p[i*3+2] = b.position.z;
        q[i*4] = b.quaternion.x; q[i*4+1] = b.quaternion.y; q[i*4+2] = b.quaternion.z; q[i*4+3] = b.quaternion.w;
        s[i] = o.mesh.scale.x;
        const col = new THREE.Color(o.mesh.userData.color || "#8fb3e8");
        c[i*3] = col.r; c[i*3+1] = col.g; c[i*3+2] = col.b;
        const paper = o.paper;
        if (paper) {
          pp[i*3] = paper.position.x; pp[i*3+1] = paper.position.y; pp[i*3+2] = paper.position.z;
          pq[i*4] = paper.quaternion.x; pq[i*4+1] = paper.quaternion.y; pq[i*4+2] = paper.quaternion.z; pq[i*4+3] = paper.quaternion.w;
          ps[i] = 1.0;
        }
      });
      gl.uniform1i(u.uCount, bs.length);
      gl.uniform3fv(u.uBPos, p); gl.uniform4fv(u.uBQuat, q);
      gl.uniform1fv(u.uBScale, s); gl.uniform3fv(u.uBColor, c);
      gl.uniform3fv(u.uPPos, pp); gl.uniform4fv(u.uPQuat, pq); gl.uniform1fv(u.uPScale, ps);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      window.__glErr = gl.getError();
    }
    return { resize, render };
  };
})();
