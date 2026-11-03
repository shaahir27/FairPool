/** Category illustrations, not photographs of an exact merchant product (I13). */
export function ProductArt({ title, small = false }: { title: string; small?: boolean }) {
  const category = /monitor|display|screen/i.test(title) ? "monitor"
    : /headphone|audio/i.test(title) ? "audio"
    : /keyboard/i.test(title) ? "keyboard"
    : /kettle/i.test(title) ? "kettle"
    : /lamp|light/i.test(title) ? "lamp"
    : /dock|hub|usb/i.test(title) ? "dock" : "parcel";
  return <div className={`product-art ${small ? "product-art-small" : ""}`} data-category={category} aria-hidden="true">
    <svg viewBox="0 0 240 180" fill="none">
      <ellipse cx="120" cy="156" rx="79" ry="8" fill="currentColor" opacity=".08" />
      {category === "monitor" ? <>
        <path d="M111 122h18l5 27h-28z" fill="currentColor" opacity=".55" />
        <path d="M87 151h66" stroke="currentColor" strokeWidth="5" strokeLinecap="round" />
        <rect x="28" y="26" width="184" height="108" rx="7" fill="currentColor" />
        <rect x="35" y="33" width="170" height="92" rx="2" fill="rgb(var(--color-product-screen))" />
        <circle cx="162" cy="59" r="16" fill="rgb(var(--color-mark))" />
        <path d="M35 101c40-62 83-55 115 2l55-23v45H35z" fill="rgb(var(--color-product-hill))" />
        <path d="M35 120c60-36 105-41 170-15v20H35z" fill="rgb(var(--color-brand-field))" opacity=".7" />
      </> : category === "audio" ? <>
        <path d="M65 103V83a55 55 0 0 1 110 0v20" stroke="currentColor" strokeWidth="18" />
        <path d="M71 82a49 49 0 0 1 98 0" stroke="rgb(var(--color-product-screen))" strokeWidth="6" />
        <rect x="49" y="88" width="39" height="61" rx="18" fill="currentColor" transform="rotate(-9 49 88)" />
        <rect x="154" y="82" width="39" height="61" rx="18" fill="currentColor" transform="rotate(9 154 82)" />
        <path d="M67 100v32M174 97v32" stroke="rgb(var(--color-mark))" strokeWidth="3" strokeLinecap="round" />
      </> : category === "keyboard" ? <>
        <path d="m30 72 176-12 13 77-176 13z" fill="currentColor" opacity=".45" />
        <path d="m28 65 176-12 13 77-176 13z" fill="currentColor" />
        {[0, 1, 2, 3].map((row) => <g key={row} transform={`translate(${43 + row * 2} ${75 + row * 14}) rotate(-4)`}>
          {Array.from({ length: row === 3 ? 5 : 11 }, (_, key) => <rect key={key} x={key * (row === 3 ? 29 : 14)} width={row === 3 ? 24 : 10} height="9" rx="2" fill={row === 0 && key === 0 ? "rgb(var(--color-mark))" : "rgb(var(--color-product-screen))"} />)}
        </g>)}
      </> : category === "kettle" ? <>
        <path d="M149 69c55-9 51 69 6 61" stroke="currentColor" strokeWidth="12" />
        <path d="m81 73-29-16 18 43" fill="currentColor" />
        <path d="M89 57h50l24 75c6 26-85 27-84 0z" fill="rgb(var(--color-product-hill))" stroke="currentColor" strokeWidth="3" />
        <path d="M87 60h57M102 51h25" stroke="currentColor" strokeWidth="7" strokeLinecap="round" />
        <path d="M94 76 88 124" stroke="rgb(var(--color-product-screen))" strokeWidth="6" strokeLinecap="round" />
      </> : category === "lamp" ? <>
        <ellipse cx="116" cy="150" rx="39" ry="7" fill="currentColor" />
        <path d="m117 145 29-64-41-30" stroke="currentColor" strokeWidth="7" strokeLinecap="round" />
        <circle cx="146" cy="81" r="7" fill="rgb(var(--color-mark))" stroke="currentColor" strokeWidth="3" />
        <path d="M107 40c-16-11-45 4-46 29l61 15c14-21 3-38-15-44z" fill="rgb(var(--color-product-hill))" stroke="currentColor" strokeWidth="3" />
        <path d="m62 71 58 14" stroke="rgb(var(--color-mark))" strokeWidth="5" />
      </> : category === "dock" ? <>
        <path d="m48 83 126-20 24 29-126 22z" fill="rgb(var(--color-product-screen))" stroke="currentColor" strokeWidth="2" />
        <path d="m48 83 24 31v24l-24-30z" fill="currentColor" opacity=".5" />
        <path d="m72 114 126-22v23L72 138z" fill="currentColor" />
        {[0, 1, 2, 3].map((port) => <path key={port} d={`m${85 + port * 25} ${120 - port * 4} 14-2`} stroke="rgb(var(--color-mark))" strokeWidth="5" />)}
        <path d="M50 87C8 78 53 40 89 44" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
      </> : <>
        <path d="m120 30 68 35-68 36-68-36z" fill="rgb(var(--color-product-screen))" stroke="currentColor" strokeWidth="2" />
        <path d="m52 65 68 36v57l-68-35z" fill="rgb(var(--color-product-hill))" stroke="currentColor" strokeWidth="2" />
        <path d="m120 101 68-36v58l-68 35z" fill="currentColor" opacity=".65" />
        <path d="m89 47 68 35v27" stroke="rgb(var(--color-mark))" strokeWidth="12" />
      </>}
    </svg>
  </div>;
}
