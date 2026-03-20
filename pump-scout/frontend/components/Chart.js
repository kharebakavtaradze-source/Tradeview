import { useEffect, useRef, useState } from 'react';
import styles from '../styles/Chart.module.css';

const LIGHTWEIGHT_CHARTS_CDN =
  'https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js';

let chartLibLoaded = false;
let chartLibPromise = null;

function loadChartLib() {
  if (chartLibLoaded) return Promise.resolve();
  if (chartLibPromise) return chartLibPromise;

  chartLibPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = LIGHTWEIGHT_CHARTS_CDN;
    script.onload = () => {
      chartLibLoaded = true;
      resolve();
    };
    script.onerror = reject;
    document.head.appendChild(script);
  });

  return chartLibPromise;
}

export default function Chart({ candles, bbData, ema50 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    loadChartLib()
      .then(() => setReady(true))
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    if (!ready || !candles || candles.length === 0 || !containerRef.current) return;

    // Destroy previous chart if any
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const LWC = window.LightweightCharts;
    if (!LWC) return;

    const container = containerRef.current;

    const chart = LWC.createChart(container, {
      width: container.clientWidth,
      height: 200,
      layout: {
        background: { color: '#13132a' },
        textColor: '#6b6b9a',
      },
      grid: {
        vertLines: { color: '#1a1a33' },
        horzLines: { color: '#1a1a33' },
      },
      crosshair: {
        mode: LWC.CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#1a1a33',
      },
      timeScale: {
        borderColor: '#1a1a33',
        timeVisible: true,
        secondsVisible: false,
      },
    });

    chartRef.current = chart;

    // Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00c853',
      downColor: '#ff4466',
      borderUpColor: '#00c853',
      borderDownColor: '#ff4466',
      wickUpColor: '#00c853',
      wickDownColor: '#ff4466',
    });

    const candleData = candles.map((c) => ({
      time: c.t,
      open: c.o,
      high: c.h,
      low: c.l,
      close: c.c,
    }));
    candleSeries.setData(candleData);

    // EMA50 line
    if (ema50) {
      const emaSeries = chart.addLineSeries({
        color: '#ff8800',
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      // Compute EMA50 across candles
      const closes = candles.map((c) => c.c);
      const k = 2 / 51;
      let emVal = closes.slice(0, 50).reduce((a, b) => a + b, 0) / 50;
      const emaPoints = [];
      for (let i = 50; i < candles.length; i++) {
        emVal = closes[i] * k + emVal * (1 - k);
        emaPoints.push({ time: candles[i].t, value: emVal });
      }
      emaSeries.setData(emaPoints);
    }

    // BB lines if provided — draw as horizontal price lines
    if (bbData && bbData.upper && bbData.lower) {
      candleSeries.createPriceLine({
        price: bbData.upper,
        color: 'rgba(180,122,255,0.6)',
        lineWidth: 1,
        lineStyle: LWC.LineStyle ? LWC.LineStyle.Dashed : 2,
        axisLabelVisible: false,
        title: 'BB+',
      });
      candleSeries.createPriceLine({
        price: bbData.lower,
        color: 'rgba(180,122,255,0.6)',
        lineWidth: 1,
        lineStyle: LWC.LineStyle ? LWC.LineStyle.Dashed : 2,
        axisLabelVisible: false,
        title: 'BB-',
      });
    }

    // Volume histogram (separate pane via price scale)
    const volSeries = chart.addHistogramSeries({
      color: 'rgba(0,229,255,0.3)',
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    const volData = candles.map((c) => ({
      time: c.t,
      value: c.v,
      color: c.c >= c.o ? 'rgba(0,200,83,0.4)' : 'rgba(255,68,102,0.4)',
    }));
    volSeries.setData(volData);

    chart.timeScale().fitContent();

    // Resize observer
    const ro = new ResizeObserver(() => {
      if (container.clientWidth > 0) {
        chart.applyOptions({ width: container.clientWidth });
      }
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [ready, candles, bbData, ema50]);

  if (error) {
    return (
      <div className={styles.chartWrapper}>
        <div className={styles.chartError}>Chart unavailable</div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className={styles.chartWrapper}>
        <div className={styles.chartLoading}>Loading chart...</div>
      </div>
    );
  }

  return (
    <div className={styles.chartWrapper}>
      <div ref={containerRef} className={styles.chartContainer} />
    </div>
  );
}
