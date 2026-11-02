import { Brand, PoolMark } from "./Brand";

export function AuthAside({ headline, valueLine }: { headline: string; valueLine: string }) {
  return (
    <section className="auth-aside" aria-label="How FairPool works">
      <div className="auth-aside-content">
      <Brand />
      <div className="pool-illustration" role="img" aria-label="Illustration of individual seats joining a pool">
        <svg viewBox="0 0 440 440" aria-hidden="true">
          {[60, 96, 132, 168, 204].map((radius, ring) => (
            <g key={radius}>
              <circle cx="220" cy="220" r={radius} fill="none" stroke="currentColor" strokeOpacity=".17" />
              {Array.from({ length: 12 + ring * 4 }, (_, index) => {
                const angle = index * Math.PI * 2 / (12 + ring * 4) + ring * .18;
                return <circle key={index} cx={220 + radius * Math.cos(angle)} cy={220 + radius * Math.sin(angle)} r={index % 7 === 0 ? 4 : 2.3} className={index % 7 === 0 ? "pool-seat" : "pool-person"} />;
              })}
            </g>
          ))}
          <circle cx="220" cy="220" r="51" className="pool-center" />
        </svg>
        <PoolMark className="pool-illustration-mark" />
        <div className="pool-stat pool-stat-entries"><span>Your entry</span><strong>One voice</strong></div>
        <div className="pool-stat pool-stat-seats"><span>Your place</span><strong>One seat</strong></div>
      </div>
      <div className="auth-story"><h2>{headline}</h2><p>{valueLine}</p></div>
      </div>
    </section>
  );
}
