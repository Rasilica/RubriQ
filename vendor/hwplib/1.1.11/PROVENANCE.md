# hwplib1.1.11 feasibility dependency

Official artifact: https://repo.maven.apache.org/maven2/kr/dogfoot/hwplib/1.1.11/hwplib-1.1.11.jar

Downloaded2026-10-10. SHA-256 fd464ff56eec7f58d463f7533da7501d4bb8261a225c20b7b19bed9e137f7e04, recorded locally; no assertion is made that this SHA was compared with a separately published digest. Upstream Apache2.0 license retained in LICENSE from commit6746c27f17ebf5277493206284aa32044a1839c4.

Used to generate the complete nonpersonal HWP5.0.3.4 sample and, from T03B4a on 2026-10-10, by the internal `tools/HwpStructureWorker.java` structure feasibility worker. No HTTP/UI integration. The worker observes top-level paragraphs and control types, not nested table content, pages or layout fidelity. The Python caller pins this JAR digest and selected provisioned runtime/source file digests; it does not attest the entire JDK dependency tree.
