declare module 'remark-math' {
  import { Plugin } from 'unified';
  const remarkMath: Plugin;
  export default remarkMath;
}

declare module 'rehype-katex' {
  import { Plugin } from 'unified';
  const rehypeKatex: Plugin;
  export default rehypeKatex;
} 