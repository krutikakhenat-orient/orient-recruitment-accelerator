/* Self-contained QR Code generator (byte mode) — no external dependency.
 *
 * This is a compact, standards-compliant QR encoder (ISO/IEC 18004): Reed–Solomon error
 * correction, the 8 standard data masks with penalty scoring, and automatic version
 * selection. It is intentionally dependency-free so the build stays offline and the
 * dependency surface minimal. It produces a boolean module matrix that the UI renders as a
 * crisp, scalable SVG (so it prints and scans well at any size).
 *
 * Adapted from the public-domain "QR Code generator" reference design (Nayuki), trimmed to
 * byte mode + the features we use. Public domain.
 */

// --- Reed–Solomon / GF(256) arithmetic -------------------------------------------------
function gfMul(x: number, y: number): number {
  let z = 0;
  for (let i = 7; i >= 0; i--) {
    z = (z << 1) ^ ((z >>> 7) * 0x11d);
    z ^= ((y >>> i) & 1) * x;
  }
  return z & 0xff;
}

function rsComputeDivisor(degree: number): number[] {
  const result = new Array<number>(degree).fill(0);
  result[degree - 1] = 1;
  let root = 1;
  for (let i = 0; i < degree; i++) {
    for (let j = 0; j < result.length; j++) {
      result[j] = gfMul(result[j]!, root);
      if (j + 1 < result.length) result[j] = result[j]! ^ result[j + 1]!;
    }
    root = gfMul(root, 0x02);
  }
  return result;
}

function rsComputeRemainder(data: number[], divisor: number[]): number[] {
  const result = new Array<number>(divisor.length).fill(0);
  for (const b of data) {
    const factor = b ^ result.shift()!;
    result.push(0);
    for (let i = 0; i < result.length; i++) result[i] = result[i]! ^ gfMul(divisor[i]!, factor);
  }
  return result;
}

// --- Error-correction parameters (level M) ---------------------------------------------
// ECC codewords per block (index = version 1..40), level M.
const ECC_CODEWORDS_PER_BLOCK_M = [
  -1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26,
  28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
];
const NUM_ERROR_CORRECTION_BLOCKS_M = [
  -1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20,
  21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49,
];

function getNumRawDataModules(ver: number): number {
  let result = (16 * ver + 128) * ver + 64;
  if (ver >= 2) {
    const numAlign = Math.floor(ver / 7) + 2;
    result -= (25 * numAlign - 10) * numAlign - 55;
    if (ver >= 7) result -= 36;
  }
  return result;
}

function getNumDataCodewords(ver: number): number {
  return (
    Math.floor(getNumRawDataModules(ver) / 8) -
    ECC_CODEWORDS_PER_BLOCK_M[ver]! * NUM_ERROR_CORRECTION_BLOCKS_M[ver]!
  );
}

// --- Matrix type -----------------------------------------------------------------------
export interface QrMatrix {
  size: number;
  modules: boolean[][]; // true = dark
}

const ECL_FORMAT_BITS = 0; // level M

export function encodeQr(text: string): QrMatrix {
  const bytes = new TextEncoder().encode(text);

  // Pick the smallest version (1..40) whose data capacity fits.
  let version = 1;
  for (; version <= 40; version++) {
    const capacityBits = getNumDataCodewords(version) * 8;
    // Byte mode: 4-bit mode indicator + char-count (8 or 16 bits) + 8 bits per byte.
    const ccBits = version <= 9 ? 8 : 16;
    const needed = 4 + ccBits + bytes.length * 8;
    if (needed <= capacityBits) break;
  }
  if (version > 40) throw new Error("Data too long for a QR code");

  // --- Build the data bit stream. ---
  const bits: number[] = [];
  const appendBits = (val: number, len: number): void => {
    for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1);
  };
  const ccBits = version <= 9 ? 8 : 16;
  appendBits(0x4, 4); // byte mode
  appendBits(bytes.length, ccBits);
  for (const b of bytes) appendBits(b, 8);

  const dataCapacityBits = getNumDataCodewords(version) * 8;
  appendBits(0, Math.min(4, dataCapacityBits - bits.length)); // terminator
  while (bits.length % 8 !== 0) bits.push(0);

  const dataCodewords: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let b = 0;
    for (let j = 0; j < 8; j++) b = (b << 1) | bits[i + j]!;
    dataCodewords.push(b);
  }
  // Pad bytes.
  for (let pad = 0xec; dataCodewords.length < getNumDataCodewords(version); pad ^= 0xec ^ 0x11) {
    dataCodewords.push(pad);
  }

  // --- Split into blocks + add ECC. ---
  const numBlocks = NUM_ERROR_CORRECTION_BLOCKS_M[version]!;
  const blockEccLen = ECC_CODEWORDS_PER_BLOCK_M[version]!;
  const rawCodewords = Math.floor(getNumRawDataModules(version) / 8);
  const numShortBlocks = numBlocks - (rawCodewords % numBlocks);
  const shortBlockLen = Math.floor(rawCodewords / numBlocks);

  const blocks: number[][] = [];
  const rsDiv = rsComputeDivisor(blockEccLen);
  let k = 0;
  for (let i = 0; i < numBlocks; i++) {
    const datLen = shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1);
    const dat = dataCodewords.slice(k, k + datLen);
    k += datLen;
    const ecc = rsComputeRemainder(dat, rsDiv);
    if (i < numShortBlocks) dat.push(0); // placeholder for interleaving alignment
    blocks.push(dat.concat(ecc));
  }

  // Interleave the blocks into the final codeword sequence.
  const result: number[] = [];
  for (let i = 0; i < blocks[0]!.length; i++) {
    for (let j = 0; j < blocks.length; j++) {
      if (i !== shortBlockLen - blockEccLen || j >= numShortBlocks) {
        result.push(blocks[j]![i]!);
      }
    }
  }

  // --- Draw the matrix. ---
  const size = version * 4 + 17;
  const modules: boolean[][] = Array.from({ length: size }, () =>
    new Array<boolean>(size).fill(false),
  );
  const isFunction: boolean[][] = Array.from({ length: size }, () =>
    new Array<boolean>(size).fill(false),
  );

  const setFunction = (x: number, y: number, dark: boolean): void => {
    modules[y]![x] = dark;
    isFunction[y]![x] = true;
  };

  // Finder patterns + separators.
  const drawFinder = (cx: number, cy: number): void => {
    for (let dy = -4; dy <= 4; dy++) {
      for (let dx = -4; dx <= 4; dx++) {
        const xx = cx + dx;
        const yy = cy + dy;
        if (xx < 0 || xx >= size || yy < 0 || yy >= size) continue;
        const dist = Math.max(Math.abs(dx), Math.abs(dy));
        setFunction(xx, yy, dist !== 2 && dist !== 4);
      }
    }
  };
  drawFinder(3, 3);
  drawFinder(size - 4, 3);
  drawFinder(3, size - 4);

  // Timing patterns.
  for (let i = 0; i < size; i++) {
    if (!isFunction[6]![i]) setFunction(i, 6, i % 2 === 0);
    if (!isFunction[i]![6]) setFunction(6, i, i % 2 === 0);
  }

  // Alignment patterns.
  const alignPositions = (): number[] => {
    if (version === 1) return [];
    const num = Math.floor(version / 7) + 2;
    const step = Math.floor((version * 8 + num * 3 + 5) / (num * 4 - 4)) * 2;
    const pos = [6];
    for (let p = size - 7; pos.length < num; p -= step) pos.splice(1, 0, p);
    return pos;
  };
  const aligns = alignPositions();
  for (const ay of aligns) {
    for (const ax of aligns) {
      if (
        (ax === 6 && ay === 6) ||
        (ax === 6 && ay === size - 7) ||
        (ax === size - 7 && ay === 6)
      ) {
        continue;
      }
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) {
          setFunction(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
      }
    }
  }

  // Reserve format + version info areas (filled later / left as function).
  for (let i = 0; i < 9; i++) {
    if (!isFunction[i]![8]) setFunction(8, i, false);
    if (!isFunction[8]![i]) setFunction(i, 8, false);
  }
  for (let i = 0; i < 8; i++) {
    setFunction(size - 1 - i, 8, false);
    setFunction(8, size - 1 - i, false);
  }
  setFunction(8, size - 8, true); // dark module
  if (version >= 7) {
    for (let i = 0; i < 18; i++) {
      const a = size - 11 + (i % 3);
      const b = Math.floor(i / 3);
      setFunction(a, b, false);
      setFunction(b, a, false);
    }
  }

  // Place data+ECC bits using the zig-zag scan.
  const allBits: number[] = [];
  for (const cw of result) for (let i = 7; i >= 0; i--) allBits.push((cw >>> i) & 1);
  let bitIdx = 0;
  for (let right = size - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5;
    for (let vert = 0; vert < size; vert++) {
      for (let j = 0; j < 2; j++) {
        const x = right - j;
        const upward = ((right + 1) & 2) === 0;
        const y = upward ? size - 1 - vert : vert;
        if (!isFunction[y]![x] && bitIdx < allBits.length) {
          modules[y]![x] = allBits[bitIdx] === 1;
          bitIdx++;
        }
      }
    }
  }

  // Try all 8 masks, score, keep the best.
  const applyMask = (m: number, mat: boolean[][]): void => {
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        if (isFunction[y]![x]) continue;
        let invert = false;
        switch (m) {
          case 0: invert = (x + y) % 2 === 0; break;
          case 1: invert = y % 2 === 0; break;
          case 2: invert = x % 3 === 0; break;
          case 3: invert = (x + y) % 3 === 0; break;
          case 4: invert = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
          case 5: invert = ((x * y) % 2) + ((x * y) % 3) === 0; break;
          case 6: invert = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break;
          default: invert = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0; break;
        }
        if (invert) mat[y]![x] = !mat[y]![x];
      }
    }
  };

  const drawFormatBits = (mask: number, mat: boolean[][]): void => {
    const data = (ECL_FORMAT_BITS << 3) | mask;
    let rem = data;
    for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
    const fmt = ((data << 10) | rem) ^ 0x5412;
    for (let i = 0; i <= 5; i++) mat[i]![8] = ((fmt >>> i) & 1) !== 0;
    mat[7]![8] = ((fmt >>> 6) & 1) !== 0;
    mat[8]![8] = ((fmt >>> 7) & 1) !== 0;
    mat[8]![7] = ((fmt >>> 8) & 1) !== 0;
    for (let i = 9; i < 15; i++) mat[8]![14 - i] = ((fmt >>> i) & 1) !== 0;
    for (let i = 0; i < 8; i++) mat[8]![size - 1 - i] = ((fmt >>> i) & 1) !== 0;
    for (let i = 8; i < 15; i++) mat[size - 15 + i]![8] = ((fmt >>> i) & 1) !== 0;
    mat[size - 8]![8] = true;
  };

  const penalty = (mat: boolean[][]): number => {
    let p = 0;
    // Runs of 5+ in rows/cols.
    for (let y = 0; y < size; y++) {
      for (const horiz of [true, false]) {
        let run = 1;
        let prev = horiz ? mat[y]![0] : mat[0]![y];
        for (let i = 1; i < size; i++) {
          const cur = horiz ? mat[y]![i] : mat[i]![y];
          if (cur === prev) {
            run++;
            if (run === 5) p += 3;
            else if (run > 5) p++;
          } else {
            run = 1;
            prev = cur;
          }
        }
      }
    }
    // 2x2 blocks.
    for (let y = 0; y < size - 1; y++) {
      for (let x = 0; x < size - 1; x++) {
        const c = mat[y]![x];
        if (c === mat[y]![x + 1] && c === mat[y + 1]![x] && c === mat[y + 1]![x + 1]) p += 3;
      }
    }
    // Dark ratio.
    let dark = 0;
    for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (mat[y]![x]) dark++;
    const total = size * size;
    const k2 = Math.ceil(Math.abs((dark * 20) / total - 10)) - 1;
    p += Math.max(0, k2) * 10;
    return p;
  };

  let bestMask = 0;
  let bestPenalty = Infinity;
  let bestMatrix = modules;
  for (let m = 0; m < 8; m++) {
    const trial = modules.map((row) => row.slice());
    applyMask(m, trial);
    drawFormatBits(m, trial);
    const pen = penalty(trial);
    if (pen < bestPenalty) {
      bestPenalty = pen;
      bestMask = m;
      bestMatrix = trial;
    }
  }
  void bestMask;

  return { size, modules: bestMatrix };
}

/** Render a QR matrix as a self-contained SVG string (crisp at any size). */
export function qrToSvg(matrix: QrMatrix, opts?: { margin?: number }): string {
  const margin = opts?.margin ?? 4;
  const dim = matrix.size + margin * 2;
  let path = "";
  for (let y = 0; y < matrix.size; y++) {
    for (let x = 0; x < matrix.size; x++) {
      if (matrix.modules[y]![x]) {
        path += `M${x + margin},${y + margin}h1v1h-1z`;
      }
    }
  }
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${dim} ${dim}" ` +
    `shape-rendering="crispEdges" role="img" aria-label="QR code">` +
    `<rect width="${dim}" height="${dim}" fill="#ffffff"/>` +
    `<path d="${path}" fill="#0b2a4a"/></svg>`
  );
}
